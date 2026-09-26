// Package server 是 images 服务的核心：注册 / 名册 / 心跳 / save / fetch。
// save：从 URL 或 base64 保存图片；fetch：把图片转成 base64 发回调用方（llm 取图用）。
package server

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"

	"github.com/QAQ-awa-QAQ/sump/images/store"
	"github.com/QAQ-awa-QAQ/sump/protocol"
)

// Config 是 images 服务的启动配置。
type Config struct {
	Name              string        // 服务名（注册用，默认 images）
	Listen            string        // 监听地址 host:port
	Center            string        // 设置中心 WS 地址
	HeartbeatInterval time.Duration // 心跳间隔（默认 15s）
	Store             *store.Store  // 图片库
	MaxBytes          int64         // 单图上限（默认 32MiB，对齐 DeepSeek 图片限制）
}

// ActionFunc 处理一次跳转动作，返回的数据会作为响应 payload 的 data。
type ActionFunc func(ctx context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error)

// Server 是 images 服务实例。
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
	if cfg.MaxBytes <= 0 {
		cfg.MaxBytes = 32 << 20
	}
	s := &Server{
		cfg:     cfg,
		logger:  logger,
		actions: map[string]ActionFunc{},
		roster:  map[string]protocol.ServiceCard{},
	}
	s.actions["save"] = s.actionSave
	s.actions["fetch"] = s.actionFetch
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
	s.logger.Printf("images 监听 %s", s.selfURL)

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
		Description: "图片服务：保存图片（URL/base64），按需转 base64 发回调用方",
		Provides: []protocol.Provide{
			{Action: "save", Input: "{url} 或 {data(base64), mime}", Output: "{id, mime, size}"},
			{Action: "fetch", Input: "{id}", Output: "{id, mime, data(base64), size}"},
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

// outConn 是 images 一侧的写封装（gorilla 不支持并发写）。
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

// serveConn 读循环：jump 交给后台 goroutine 处理（save 含下载可能较慢，不阻塞读循环）。
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
		go s.handleJump(c, env)
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

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
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

// actionSave 保存一张图片：URL 或 base64 二选一。
func (s *Server) actionSave(_ context.Context, _ protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var p protocol.ImageSavePayload
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	var data []byte
	var mimeHint string
	var err error
	switch {
	case strings.TrimSpace(p.URL) != "":
		data, mimeHint, err = fetchURL(p.URL, s.cfg.MaxBytes)
	case strings.TrimSpace(p.Data) != "":
		data, err = base64.StdEncoding.DecodeString(p.Data)
	default:
		return nil, errors.New("save: url 或 data 必填")
	}
	if err != nil {
		return nil, err
	}
	if len(data) == 0 {
		return nil, errors.New("save: 图片为空")
	}
	if int64(len(data)) > s.cfg.MaxBytes {
		return nil, fmt.Errorf("save: 图片超过 %d 字节上限", s.cfg.MaxBytes)
	}
	mime := p.Mime
	if mime == "" {
		mime = mimeHint
	}
	if mime == "" {
		mime = http.DetectContentType(data)
	}
	id, err := s.cfg.Store.Save(data, mime)
	if err != nil {
		return nil, fmt.Errorf("保存失败: %w", err)
	}
	s.logger.Printf("已保存图片 %s（%s, %d 字节）", id, mime, len(data))
	return protocol.ImageSaveResult{ID: id, Mime: mime, Size: int64(len(data))}, nil
}

// actionFetch 把图片转成 base64 发回调用方。
func (s *Server) actionFetch(_ context.Context, _ protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var p protocol.ImageFetchPayload
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	if p.ID == "" {
		return nil, errors.New("fetch: id 必填")
	}
	data, mime, err := s.cfg.Store.Load(p.ID)
	if err != nil {
		return nil, err
	}
	return protocol.ImageFetchResult{
		ID:   p.ID,
		Mime: mime,
		Data: base64.StdEncoding.EncodeToString(data),
		Size: int64(len(data)),
	}, nil
}

// fetchURL 下载图片：限时 30s、限制大小（多读 1 字节探测超限）。
func fetchURL(url string, maxBytes int64) ([]byte, string, error) {
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return nil, "", fmt.Errorf("下载失败: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, "", fmt.Errorf("下载失败: HTTP %d", resp.StatusCode)
	}
	if maxBytes <= 0 {
		maxBytes = 32 << 20
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxBytes+1))
	if err != nil {
		return nil, "", fmt.Errorf("读取下载内容失败: %w", err)
	}
	if int64(len(data)) > maxBytes {
		return nil, "", fmt.Errorf("下载内容超过 %d 字节上限", maxBytes)
	}
	mime := resp.Header.Get("Content-Type")
	if i := strings.IndexByte(mime, ';'); i >= 0 {
		mime = mime[:i]
	}
	return data, strings.TrimSpace(mime), nil
}
