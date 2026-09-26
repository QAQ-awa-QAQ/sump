// Package server 是 memory 服务的核心：注册 / 名册 / 心跳 / recall / store。
// recall 收到 llm 托管的任务上下文 → 查会话历史并组装记忆 → 以 resume 发回 llm（触发其“完全启动”）。
package server

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/vmihailenco/msgpack/v5"

	"github.com/QAQ-awa-QAQ/sump/memory/compose"
	"github.com/QAQ-awa-QAQ/sump/memory/store"
	"github.com/QAQ-awa-QAQ/sump/protocol"
)

// Config 是 memory 服务的启动配置。
type Config struct {
	Name              string        // 服务名（注册用，默认 memory）
	Listen            string        // 监听地址 host:port
	Center            string        // 设置中心 WS 地址
	HeartbeatInterval time.Duration // 心跳间隔（默认 15s）
	Store             *store.Store  // 会话库
	HistoryLimit      int           // recall 返回的最近消息条数（默认 12）
}

// ActionFunc 处理一次跳转动作，返回的数据会作为响应 payload 的 data。
type ActionFunc func(ctx context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error)

// Server 是 memory 服务实例。
type Server struct {
	cfg    Config
	logger *log.Logger

	actions map[string]ActionFunc

	mu      sync.Mutex
	roster  map[string]protocol.ServiceCard
	selfURL string // 对外地址（Start 成功后有效）

	center *protocol.Client

	httpSrv *http.Server
}

// New 创建实例并注册动作。
func New(cfg Config, logger *log.Logger) *Server {
	if cfg.HeartbeatInterval <= 0 {
		cfg.HeartbeatInterval = 15 * time.Second
	}
	if cfg.HistoryLimit <= 0 {
		cfg.HistoryLimit = 12
	}
	s := &Server{
		cfg:     cfg,
		logger:  logger,
		actions: map[string]ActionFunc{},
		roster:  map[string]protocol.ServiceCard{},
	}
	s.actions["recall"] = s.actionRecall
	s.actions["store"] = s.actionStore
	return s
}

// WsURL 返回自己的对外地址（Start 成功后有效）。
func (s *Server) WsURL() string { return s.selfURL }

// Start 启动 WS 服务端、注册到设置中心并开始心跳。
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
	s.logger.Printf("memory 监听 %s", s.selfURL)

	if err := s.register(ctx); err != nil {
		return fmt.Errorf("注册失败: %w", err)
	}
	go s.heartbeatLoop(ctx)
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
		Description: "记忆服务：会话历史存储与上下文组装（recall 后向 llm 回发 resume）",
		Provides: []protocol.Provide{
			{Action: "recall", Input: "任务上下文 {conversation_id, messages, boss}", Output: "受理回执；随后向调用方发送 resume（注入记忆后的上下文）"},
			{Action: "store", Input: "{conversation_id, role, content}", Output: "落库回执"},
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

// ---------- WS 服务端（接受 jump） ----------

var upgrader = websocket.Upgrader{
	CheckOrigin: func(*http.Request) bool { return true },
}

// outConn 是 memory 一侧的写封装（gorilla 不支持并发写）。
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

// actionStore 记一条对话消息（幂等：与上一条完全相同时跳过）。
func (s *Server) actionStore(_ context.Context, _ protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var p protocol.StorePayload
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	if strings.TrimSpace(p.Content) == "" {
		return map[string]any{}, nil
	}
	cid := p.ConversationID
	if cid == "" {
		cid = "default"
	}
	if err := s.cfg.Store.Append(cid, p.Role, p.Content); err != nil {
		return nil, fmt.Errorf("落库失败: %w", err)
	}
	return map[string]any{}, nil
}

// actionRecall 是“完全启动”链的上半段：收下任务上下文 → 组装（注入记忆）→ 以 resume 发回调用方。
func (s *Server) actionRecall(_ context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var p protocol.RecallPayload
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	tc := p.Context
	if len(tc.Messages) == 0 {
		return nil, errors.New("recall: context.messages 为空")
	}
	cid := tc.ConversationID
	if cid == "" {
		cid = "default"
	}

	history, err := s.cfg.Store.Recent(cid, s.cfg.HistoryLimit)
	if err != nil {
		return nil, fmt.Errorf("查询历史失败: %w", err)
	}
	// 去重：历史尾部与任务上下文尾部的对话消息相同时裁掉——任务链里已有的消息不重复注入。
	history = compose.TrimOverlap(history, compose.ConversationTail(tc.Messages))

	text := compose.BuildText(history)
	final := compose.Inject(tc.Messages, text)

	raw, err := protocol.EncodePayload(protocol.ResumePayload{Context: protocol.TaskContext{
		ConversationID: cid,
		Messages:       final,
		Boss:           tc.Boss,
	}})
	if err != nil {
		return nil, err
	}
	if err := s.fireResume(env, raw); err != nil {
		return nil, err
	}

	return map[string]any{"status": "accepted"}, nil
}

// fireResume 向调用方（llm 服务）发送组装完成的上下文——“过程中的 boss 是 llm”。
// resolve 失败会同步返回（调用方可收到错误）；投递本身异步进行（发出即完）。
func (s *Server) fireResume(req protocol.Envelope, raw msgpack.RawMessage) error {
	target := req.From
	if target == "" {
		return errors.New("recall: 请求缺少 from，无法回发 resume")
	}
	name, addr, err := s.resolve(target)
	if err != nil {
		return err
	}
	go func() {
		c, err := protocol.Dial(addr, nil)
		if err != nil {
			s.logger.Printf("resume 连接 %s 失败: %v", addr, err)
			return
		}
		defer c.Close()
		env, err := protocol.NewEnvelope(protocol.TypeJump, s.cfg.Name, name, req.Trace, protocol.JumpPayload{Action: "resume", Input: raw})
		if err != nil {
			s.logger.Printf("resume 构造失败: %v", err)
			return
		}
		env.Boss = target
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()
		if _, err := c.Call(ctx, env); err != nil {
			s.logger.Printf("resume 未确认送达: %v", err)
		}
	}()
	return nil
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
