// Package server 是 qq 服务的核心：注册 / 名册 / 心跳 / deliver，
// 以及 QQ 私聊消息 → user_message 任务链的桥接（NapCat/OneBot 11 正向 WS）。
// 零信任：仅主人私聊触发任务；群聊本批次未启用。
package server

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/vmihailenco/msgpack/v5"

	"github.com/QAQ-awa-QAQ/sump/protocol"
	"github.com/QAQ-awa-QAQ/sump/qq/napcat"
)

// Config 是 qq 服务的启动配置。
type Config struct {
	Name              string        // 服务名（注册用，默认 qq）
	Listen            string        // 监听地址 host:port
	Center            string        // 设置中心 WS 地址
	HeartbeatInterval time.Duration // 心跳间隔（默认 15s）
	NapCatURL         string        // NapCat 正向 WS 地址
	NapCatToken       string        // access_token（可选）
	Owner             string        // 主人 QQ（唯一授权私聊用户；留空则拒绝所有私聊）
	Agent             string        // 任务跳转目标（agentloop 服务名，默认 agentloop）
	Images            string        // 图片服务名（默认 images）
}

// ActionFunc 处理一次跳转动作，返回的数据会作为响应 payload 的 data。
type ActionFunc func(ctx context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error)

// Server 是 qq 服务实例。
type Server struct {
	cfg    Config
	logger *log.Logger
	napcat *napcat.Client

	mu      sync.Mutex
	roster  map[string]protocol.ServiceCard
	selfURL string // 对外地址（Start 成功后有效）

	locksMu sync.Mutex
	locks   map[string]*sync.Mutex // 会话级串行锁（防同一会话消息乱序）

	actions map[string]ActionFunc

	center  *protocol.Client
	httpSrv *http.Server
}

// New 创建实例并注册动作。
func New(cfg Config, logger *log.Logger) *Server {
	if cfg.HeartbeatInterval <= 0 {
		cfg.HeartbeatInterval = 15 * time.Second
	}
	if cfg.Agent == "" {
		cfg.Agent = "agentloop"
	}
	if cfg.Images == "" {
		cfg.Images = "images"
	}
	s := &Server{
		cfg:     cfg,
		logger:  logger,
		roster:  map[string]protocol.ServiceCard{},
		locks:   map[string]*sync.Mutex{},
		actions: map[string]ActionFunc{},
	}
	s.actions["deliver"] = s.actionDeliver
	s.napcat = napcat.New(napcat.Config{
		URL:       cfg.NapCatURL,
		Token:     cfg.NapCatToken,
		Logger:    logger,
		OnMessage: s.onQQEvent,
	})
	return s
}

// WsURL 返回自己的对外地址（Start 成功后有效）。
func (s *Server) WsURL() string { return s.selfURL }

// Start 启动 WS 服务端、注册设置中心、开始心跳与 NapCat 连接循环。
func (s *Server) Start(ctx context.Context) error {
	ln, err := net.Listen("tcp", s.cfg.Listen)
	if err != nil {
		return err
	}
	s.selfURL = "ws://" + ln.Addr().String() + "/ws"

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", s.handleWS)
	s.httpSrv = &http.Server{Handler: mux}
	go func() {
		if err := s.httpSrv.Serve(ln); err != nil && err != http.ErrServerClosed {
			s.logger.Printf("服务退出: %v", err)
		}
	}()
	s.logger.Printf("qq 监听 %s", s.selfURL)
	if s.cfg.Owner == "" {
		s.logger.Printf("警告: 未配置主人 QQ（-owner），所有私聊都将被拒绝")
	}

	if err := s.register(ctx); err != nil {
		return fmt.Errorf("注册失败: %w", err)
	}
	go s.heartbeatLoop(ctx)
	go s.napcat.Run(ctx)
	return nil
}

// Shutdown 关闭 WS 服务端与到设置中心的连接。
func (s *Server) Shutdown() {
	if s.httpSrv != nil {
		_ = s.httpSrv.Close()
	}
	if s.center != nil {
		_ = s.center.Close()
	}
}

// Roster 返回当前名册快照（按服务名排序）。
func (s *Server) Roster() []protocol.ServiceCard {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]protocol.ServiceCard, 0, len(s.roster))
	for _, c := range s.roster {
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

func (s *Server) register(ctx context.Context) error {
	c, err := protocol.Dial(s.cfg.Center, s.onCenterEvent)
	if err != nil {
		return err
	}
	s.center = c

	env, err := protocol.NewEnvelope(protocol.TypeRegister, s.cfg.Name, "settings-center", "", protocol.RegisterPayload{
		Name:        s.cfg.Name,
		Addr:        s.selfURL,
		Description: "QQ 接入（NapCat/OneBot 11 · 仅私聊）：消息 → 任务链；deliver → 发回 QQ",
		Provides: []protocol.Provide{
			{Action: "deliver", Input: "{text, conversation_id}", Output: "回执（已发回 QQ）"},
		},
		Settings: []protocol.Setting{{Key: "conn.default_ttl", Default: "5m"}},
	})
	if err != nil {
		return err
	}
	resp, err := c.Call(ctx, env)
	if err != nil {
		return err
	}
	var rp protocol.ResponsePayload
	if err := resp.DecodePayload(&rp); err != nil {
		return err
	}
	if !rp.OK {
		return errors.New("register rejected: " + rp.Error)
	}
	var roster protocol.RosterPayload
	if err := protocol.DecodeRaw(rp.Data, &roster); err != nil {
		return err
	}
	s.setRoster(roster)
	s.logger.Printf("注册成功（%s），名册 %d 个服务 (rev %d)", s.selfURL, len(roster.Services), roster.Revision)
	return nil
}

func (s *Server) heartbeatLoop(ctx context.Context) {
	t := time.NewTicker(s.cfg.HeartbeatInterval)
	defer t.Stop()
	for {
		select {
		case <-t.C:
			env, err := protocol.NewEnvelope(protocol.TypeHeartbeat, s.cfg.Name, "settings-center", "", protocol.HeartbeatPayload{Status: "ok"})
			if err == nil && s.center != nil {
				_ = s.center.Send(env)
			}
		case <-ctx.Done():
			return
		}
	}
}

func (s *Server) onCenterEvent(env protocol.Envelope) {
	switch env.Type {
	case protocol.TypeRoster:
		var r protocol.RosterPayload
		if err := env.DecodePayload(&r); err != nil {
			s.logger.Printf("roster 解析失败: %v", err)
			return
		}
		s.setRoster(r)
		s.logger.Printf("roster 更新: %d 个服务 (rev %d)", len(r.Services), r.Revision)
	default:
		s.logger.Printf("未知事件: %s", env.Type)
	}
}

func (s *Server) setRoster(r protocol.RosterPayload) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.roster = make(map[string]protocol.ServiceCard, len(r.Services))
	for _, c := range r.Services {
		s.roster[c.Name] = c
	}
}

// ---------- WS 服务端（接受 jump：deliver） ----------

var upgrader = websocket.Upgrader{
	CheckOrigin: func(*http.Request) bool { return true },
}

// outConn 是 qq 一侧的写封装（gorilla 不支持并发写）。
type outConn struct {
	ws     *websocket.Conn
	mu     sync.Mutex
	closed bool
}

// Send 发送一条消息（线程安全）。
func (c *outConn) Send(env protocol.Envelope) error {
	data, err := protocol.Marshal(env)
	if err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return protocol.ErrConnClosed
	}
	return c.ws.WriteMessage(websocket.BinaryMessage, data)
}

// Close 关闭连接。
func (c *outConn) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return nil
	}
	c.closed = true
	return c.ws.Close()
}

func (s *Server) handleWS(w http.ResponseWriter, r *http.Request) {
	ws, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		s.logger.Printf("升级失败: %v", err)
		return
	}
	go s.serveConn(ws)
}

func (s *Server) serveConn(ws *websocket.Conn) {
	c := &outConn{ws: ws}
	defer c.Close()
	for {
		_, data, err := ws.ReadMessage()
		if err != nil {
			return
		}
		env, err := protocol.Unmarshal(data)
		if err != nil {
			s.logger.Printf("坏帧: %v", err)
			continue
		}
		if env.Type != protocol.TypeJump {
			s.replyError(c, env, "unsupported message type: "+env.Type)
			continue
		}
		s.handleJump(c, env)
	}
}

func (s *Server) handleJump(c *outConn, env protocol.Envelope) {
	var jp protocol.JumpPayload
	if err := env.DecodePayload(&jp); err != nil {
		s.replyError(c, env, "bad jump payload")
		return
	}
	fn, ok := s.actions[jp.Action]
	if !ok {
		s.replyError(c, env, "unknown action: "+jp.Action)
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	out, err := fn(ctx, env, jp)
	if err != nil {
		s.replyError(c, env, err.Error())
		return
	}
	data, err := protocol.EncodePayload(out)
	if err != nil {
		s.replyError(c, env, "encode result failed")
		return
	}
	resp, err := protocol.NewResponse(env, s.cfg.Name, protocol.ResponsePayload{OK: true, Data: data})
	if err == nil {
		_ = c.Send(resp)
	}
}

func (s *Server) replyError(c *outConn, req protocol.Envelope, msg string) {
	resp, err := protocol.NewResponse(req, s.cfg.Name, protocol.ResponsePayload{OK: false, Error: msg})
	if err == nil {
		_ = c.Send(resp)
	}
}

// ---------- 动作 ----------

// actionDeliver 是 boss 约定动作：把任务结果发回原 QQ 会话。
func (s *Server) actionDeliver(ctx context.Context, _ protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var p protocol.DeliverPayload
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	if strings.TrimSpace(p.Text) == "" {
		return nil, errors.New("deliver: text 为空")
	}
	kind, id, ok := parseConversation(p.ConversationID)
	if !ok {
		return nil, fmt.Errorf("deliver: 无法解析会话标识 %q", p.ConversationID)
	}
	if kind != "private" {
		return nil, errors.New("deliver: 群聊未启用")
	}
	uid, err := strconv.ParseInt(id, 10, 64)
	if err != nil {
		return nil, fmt.Errorf("deliver: 会话 id 无效 %q", id)
	}
	if err := s.sendPrivate(ctx, uid, p.Text); err != nil {
		return nil, fmt.Errorf("发送 QQ 消息失败: %w", err)
	}
	return map[string]any{}, nil
}

// ---------- QQ 私聊 → 任务链 ----------

// onQQEvent 处理一条 NapCat 消息事件（napcat 客户端的回调 goroutine）。
func (s *Server) onQQEvent(ev napcat.Event) {
	if ev.MessageType != "private" {
		s.logger.Printf("忽略非私聊消息（群聊未启用）: type=%s group=%d", ev.MessageType, ev.GroupID)
		return
	}
	uid := strconv.FormatInt(ev.UserID, 10)
	if s.cfg.Owner == "" || uid != s.cfg.Owner {
		s.logger.Printf("拒绝非主人私聊: user_id=%s", uid)
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if err := s.sendPrivate(ctx, ev.UserID, "抱歉，你不是授权用户，已拒绝执行。"); err != nil {
			s.logger.Printf("发送拒绝语失败: %v", err)
		}
		return
	}

	// 会话级串行：同一会话逐条处理，不阻塞其他会话。
	lock := s.convLock(uid)
	lock.Lock()
	defer lock.Unlock()

	text := ev.Text()
	var ids []string
	for _, u := range ev.ImageURLs() {
		id, err := s.saveImage(u)
		if err != nil {
			s.logger.Printf("保存图片失败: %v", err)
			if strings.TrimSpace(text) == "" {
				text = "[图片]"
			} else {
				text += "\n[图片]"
			}
			continue
		}
		ids = append(ids, id)
	}
	if strings.TrimSpace(text) == "" && len(ids) == 0 {
		return
	}

	cid := "qq:private:" + uid
	payload := map[string]any{"text": text, "conversation_id": cid}
	if len(ids) > 0 {
		payload["images"] = ids
	}
	if err := s.callAgent("user_message", payload); err != nil {
		s.logger.Printf("user_message 未受理: %v", err)
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if err2 := s.sendPrivate(ctx, ev.UserID, "抱歉，服务暂时不可用。"); err2 != nil {
			s.logger.Printf("发送失败提示失败: %v", err2)
		}
	}
}

// saveImage 把图片 URL 交给 images 服务保存，返回图片 id。
func (s *Server) saveImage(url string) (string, error) {
	targetName, targetAddr, err := s.resolve(s.cfg.Images)
	if err != nil {
		return "", err
	}
	raw, err := protocol.EncodePayload(protocol.ImageSavePayload{URL: url})
	if err != nil {
		return "", err
	}
	data, err := s.callService(targetName, targetAddr, "save", raw, protocol.NewID(), s.cfg.Name)
	if err != nil {
		return "", err
	}
	var res protocol.ImageSaveResult
	if err := protocol.DecodeRaw(data, &res); err != nil || res.ID == "" {
		return "", errors.New("images.save 返回无效")
	}
	return res.ID, nil
}

// callAgent 向 agentloop 发 user_message（等受理回执；boss=本服务）。
func (s *Server) callAgent(action string, payload any) error {
	targetName, targetAddr, err := s.resolve(s.cfg.Agent)
	if err != nil {
		return err
	}
	raw, err := protocol.EncodePayload(payload)
	if err != nil {
		return err
	}
	_, err = s.callService(targetName, targetAddr, action, raw, protocol.NewID(), s.cfg.Name)
	return err
}

// sendPrivate 私聊发送一条文本。
func (s *Server) sendPrivate(ctx context.Context, uid int64, text string) error {
	_, err := s.napcat.Call(ctx, "send_msg", map[string]any{
		"message_type": "private",
		"user_id":      uid,
		"message":      text,
	})
	return err
}

// parseConversation 解析会话标识（qq:private:<uid> / qq:group:<gid>）。
func parseConversation(cid string) (kind, id string, ok bool) {
	parts := strings.SplitN(cid, ":", 3)
	if len(parts) != 3 || parts[0] != "qq" || parts[1] == "" || parts[2] == "" {
		return "", "", false
	}
	return parts[1], parts[2], true
}

// convLock 返回会话级互斥锁。
func (s *Server) convLock(key string) *sync.Mutex {
	s.locksMu.Lock()
	defer s.locksMu.Unlock()
	l := s.locks[key]
	if l == nil {
		l = &sync.Mutex{}
		s.locks[key] = l
	}
	return l
}

// ---------- 服务间访问 ----------

// callService 访问目标服务：发一跳并等响应（短连接）。
func (s *Server) callService(targetName, targetAddr, action string, input msgpack.RawMessage, trace, boss string) (msgpack.RawMessage, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	c, err := protocol.Dial(targetAddr, nil)
	if err != nil {
		return nil, fmt.Errorf("连接 %s 失败: %w", targetAddr, err)
	}
	defer c.Close()
	env, err := protocol.NewEnvelope(protocol.TypeJump, s.cfg.Name, targetName, trace, protocol.JumpPayload{Action: action, Input: input})
	if err != nil {
		return nil, err
	}
	env.Boss = boss
	resp, err := c.Call(ctx, env)
	if err != nil {
		return nil, fmt.Errorf("跳转 %s(%s) 失败: %w", targetName, action, err)
	}
	var rp protocol.ResponsePayload
	if err := resp.DecodePayload(&rp); err != nil {
		return nil, err
	}
	if !rp.OK {
		return nil, errors.New("远端错误: " + rp.Error)
	}
	return rp.Data, nil
}

// resolve 解析目标：支持 "self" 与服务名（查名册）。
func (s *Server) resolve(to string) (name, addr string, err error) {
	if to == "self" {
		return s.cfg.Name, s.selfURL, nil
	}
	s.mu.Lock()
	card, ok := s.roster[to]
	s.mu.Unlock()
	if !ok {
		return "", "", fmt.Errorf("未知目标服务: %s", to)
	}
	return card.Name, card.Addr, nil
}
