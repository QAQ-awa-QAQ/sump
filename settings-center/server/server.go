// Package server 是设置中心的 WS 服务端：接受连接、分发消息。
package server

import (
	"log"
	"net"
	"net/http"
	"sync"

	"github.com/gorilla/websocket"

	"github.com/QAQ-awa-QAQ/sump/protocol"
	"github.com/QAQ-awa-QAQ/sump/settings-center/hub"
)

// Server 是设置中心服务实例。
type Server struct {
	hub     *hub.Hub
	httpSrv *http.Server
	ln      net.Listener
	logger  *log.Logger
}

var upgrader = websocket.Upgrader{
	// 服务间互访，本机 / 内网使用，放开 Origin 校验。
	CheckOrigin: func(*http.Request) bool { return true },
}

// Start 在 addr 上启动服务（非阻塞）；addr 用 ":0" 可随机端口。
func Start(addr string, logger *log.Logger) (*Server, error) {
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return nil, err
	}
	h := hub.New(logger)
	h.PutSelf(protocol.ServiceCard{
		Name:        "settings-center",
		Addr:        "ws://" + ln.Addr().String() + "/ws",
		Description: "服务注册 · 全局信息 · 设置与调度",
		Provides: []protocol.Provide{
			{Action: "ping", Output: "pong（连通性测试）"},
			{Action: "roster", Output: "最新全量服务清单（DNS 式拉取）"},
		},
	})
	s := &Server{hub: h, ln: ln, logger: logger}
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", s.handleWS)
	s.httpSrv = &http.Server{Handler: mux}
	go func() {
		if err := s.httpSrv.Serve(ln); err != nil && err != http.ErrServerClosed {
			logger.Printf("服务退出: %v", err)
		}
	}()
	logger.Printf("settings-center 监听 ws://%s/ws", ln.Addr())
	return s, nil
}

// Addr 返回实际监听地址（host:port）。
func (s *Server) Addr() string { return s.ln.Addr().String() }

// Shutdown 关闭服务。
func (s *Server) Shutdown() error { return s.httpSrv.Close() }

func (s *Server) handleWS(w http.ResponseWriter, r *http.Request) {
	ws, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		s.logger.Printf("升级失败: %v", err)
		return
	}
	sc := &serverConn{ws: ws, hub: s.hub, logger: s.logger}
	go sc.serve()
}

// serverConn 是一条已升级的服务连接。
type serverConn struct {
	ws     *websocket.Conn
	hub    *hub.Hub
	logger *log.Logger

	mu     sync.Mutex // 写锁（gorilla 不支持并发写）
	name   string     // 注册后的服务名（未注册为空）
	closed bool
}

// Send 发送一条消息（线程安全）。
func (c *serverConn) Send(env protocol.Envelope) error {
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
func (c *serverConn) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return nil
	}
	c.closed = true
	return c.ws.Close()
}

func (c *serverConn) serve() {
	defer func() {
		if c.name != "" {
			c.hub.Disconnect(c.name, c)
			c.logger.Printf("连接断开: %s", c.name)
		}
		_ = c.Close()
	}()
	for {
		_, data, err := c.ws.ReadMessage()
		if err != nil {
			return
		}
		env, err := protocol.Unmarshal(data)
		if err != nil {
			c.logger.Printf("坏帧: %v", err)
			continue
		}
		c.dispatch(env)
	}
}

func (c *serverConn) dispatch(env protocol.Envelope) {
	switch env.Type {
	case protocol.TypeRegister:
		c.handleRegister(env)
	case protocol.TypeHeartbeat:
		c.hub.NoteSeen(env.From)
	case protocol.TypeJump:
		c.handleJump(env)
	default:
		c.replyError(env, "unsupported message type: "+env.Type)
	}
}

func (c *serverConn) handleRegister(env protocol.Envelope) {
	var reg protocol.RegisterPayload
	if err := env.DecodePayload(&reg); err != nil {
		c.replyError(env, "bad register payload")
		return
	}
	if reg.Name == "" || reg.Addr == "" {
		c.replyError(env, "register: name and addr required")
		return
	}

	c.name = reg.Name
	roster := c.hub.Register(reg.Card(), c)

	data, err := protocol.EncodePayload(roster)
	if err != nil {
		c.replyError(env, "encode roster failed")
		return
	}
	resp, err := protocol.NewResponse(env, "settings-center", protocol.ResponsePayload{OK: true, Data: data})
	if err == nil {
		_ = c.Send(resp)
	}
	c.hub.Broadcast(roster)
	c.logger.Printf("注册: %s (%s)", reg.Name, reg.Addr)
}

func (c *serverConn) handleJump(env protocol.Envelope) {
	var jp protocol.JumpPayload
	if err := env.DecodePayload(&jp); err != nil {
		c.replyError(env, "bad jump payload")
		return
	}
	switch jp.Action {
	case "ping":
		c.replyData(env, map[string]any{"pong": true, "who": "settings-center"})
	case "roster":
		// DNS 式拉取：返回最新全量清单（推送丢失 / 服务重启后自愈用）
		c.replyData(env, c.hub.Snapshot())
	default:
		c.replyError(env, "unknown action: "+jp.Action)
	}
}

// replyData 构造并发送一个成功响应（data 为任意可编码值）。
func (c *serverConn) replyData(req protocol.Envelope, v any) {
	data, err := protocol.EncodePayload(v)
	if err != nil {
		c.replyError(req, "encode failed")
		return
	}
	resp, err := protocol.NewResponse(req, "settings-center", protocol.ResponsePayload{OK: true, Data: data})
	if err == nil {
		_ = c.Send(resp)
	}
}

func (c *serverConn) replyError(req protocol.Envelope, msg string) {
	resp, err := protocol.NewResponse(req, "settings-center", protocol.ResponsePayload{OK: false, Error: msg})
	if err != nil {
		return
	}
	_ = c.Send(resp)
}
