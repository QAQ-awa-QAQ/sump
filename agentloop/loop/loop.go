package loop

// agentloop 服务的核心：注册、名册、心跳与跳转处理。
// 按 DESIGN.md 的“自我跳转”设计：agentloop 不持有循环——它是单步推理器，
// 每收到一次输入产出一次结果（下一步由跳转推进）。
// M1 骨架先实现基础设施（注册 / echo / 跳转调试），LLM 推理在 M2 接入。

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"sort"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/vmihailenco/msgpack/v5"

	"github.com/QAQ-awa-QAQ/sump/agentloop/llm"
	"github.com/QAQ-awa-QAQ/sump/protocol"
)

// Config 是 agentloop 的启动配置（引导只靠它：自己的名字/地址 + 设置中心地址）。
type Config struct {
	Name              string        // 服务名（注册用）
	Listen            string        // 监听地址 host:port
	Center            string        // 设置中心 WS 地址
	HeartbeatInterval time.Duration // 心跳间隔（默认 15s）
	Memory            string        // 记忆服务名（默认 memory——“完全启动”链的另一半）
	Images            string        // 图片服务名（默认 images——推理前取图内联）
	LLM               llm.Client    // 单步推理的 LLM 客户端（user_message / step 必需；nil 时相关动作报错）
}

// ActionFunc 处理一次跳转动作，返回的数据会作为响应 payload 的 data。
type ActionFunc func(ctx context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error)

// Loop 是 agentloop 服务实例。
type Loop struct {
	cfg    Config
	logger *log.Logger

	actions map[string]ActionFunc

	mu      sync.Mutex
	roster  map[string]protocol.ServiceCard
	selfURL string // 对外地址（Start 成功后有效）

	center *protocol.Client

	httpSrv *http.Server
}

// New 创建实例并注册内置动作。
func New(cfg Config, logger *log.Logger) *Loop {
	if cfg.HeartbeatInterval <= 0 {
		cfg.HeartbeatInterval = 15 * time.Second
	}
	if cfg.Memory == "" {
		cfg.Memory = "memory"
	}
	if cfg.Images == "" {
		cfg.Images = "images"
	}
	l := &Loop{
		cfg:     cfg,
		logger:  logger,
		actions: map[string]ActionFunc{},
		roster:  map[string]protocol.ServiceCard{},
	}
	l.actions["echo"] = l.actionEcho
	l.actions["debug_jump"] = l.actionDebugJump
	l.actions["user_message"] = l.actionUserMessage
	l.actions["step"] = l.actionStep
	l.actions["resume"] = l.actionResume
	return l
}

// WsURL 返回自己的对外地址（Start 成功后有效）。
func (l *Loop) WsURL() string { return l.selfURL }

// Start 启动 WS 服务端、注册到设置中心并开始心跳。
func (l *Loop) Start(ctx context.Context) error {
	ln, err := net.Listen("tcp", l.cfg.Listen)
	if err != nil {
		return err
	}
	l.selfURL = "ws://" + ln.Addr().String() + "/ws"

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", l.handleWS)
	l.httpSrv = &http.Server{Handler: mux}
	go func() {
		if err := l.httpSrv.Serve(ln); err != nil && err != http.ErrServerClosed {
			l.logger.Printf("服务退出: %v", err)
		}
	}()
	l.logger.Printf("agentloop 监听 %s", l.selfURL)

	if err := l.register(ctx); err != nil {
		return fmt.Errorf("注册失败: %w", err)
	}
	go l.heartbeatLoop(ctx)
	return nil
}

// Shutdown 关闭 WS 服务端与到设置中心的连接。
func (l *Loop) Shutdown() {
	if l.httpSrv != nil {
		_ = l.httpSrv.Close()
	}
	if l.center != nil {
		_ = l.center.Close()
	}
}

// Roster 返回当前名册快照（按服务名排序）。
func (l *Loop) Roster() []protocol.ServiceCard {
	l.mu.Lock()
	defer l.mu.Unlock()
	out := make([]protocol.ServiceCard, 0, len(l.roster))
	for _, c := range l.roster {
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

func (l *Loop) register(ctx context.Context) error {
	c, err := protocol.Dial(l.cfg.Center, l.onCenterEvent)
	if err != nil {
		return err
	}
	l.center = c

	env, err := protocol.NewEnvelope(protocol.TypeRegister, l.cfg.Name, "settings-center", "", protocol.RegisterPayload{
		Name:        l.cfg.Name,
		Addr:        l.selfURL,
		Description: "LLM 单步推理：任务先经记忆服务托管，收到来自记忆的 resume 才完全启动（调 LLM API）",
		Provides: []protocol.Provide{
			{Action: "user_message", Input: "用户消息文本 {text}", Output: "受理回执（最终结果由 deliver 另行送达）"},
			{Action: "echo", Input: "任意", Output: "原样返回（测试用）"},
			{Action: "debug_jump", Input: "{to, action, input}", Output: "目标服务的响应数据（调试用）"},
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
	l.setRoster(roster)
	l.logger.Printf("注册成功（%s），名册 %d 个服务 (rev %d)", l.selfURL, len(roster.Services), roster.Revision)
	return nil
}

func (l *Loop) heartbeatLoop(ctx context.Context) {
	t := time.NewTicker(l.cfg.HeartbeatInterval)
	defer t.Stop()
	for {
		select {
		case <-t.C:
			env, err := protocol.NewEnvelope(protocol.TypeHeartbeat, l.cfg.Name, "settings-center", "", protocol.HeartbeatPayload{Status: "ok"})
			if err == nil && l.center != nil {
				_ = l.center.Send(env)
			}
		case <-ctx.Done():
			return
		}
	}
}

func (l *Loop) onCenterEvent(env protocol.Envelope) {
	switch env.Type {
	case protocol.TypeRoster:
		var r protocol.RosterPayload
		if err := env.DecodePayload(&r); err != nil {
			l.logger.Printf("roster 解析失败: %v", err)
			return
		}
		l.setRoster(r)
		l.logger.Printf("roster 更新: %d 个服务 (rev %d)", len(r.Services), r.Revision)
	default:
		l.logger.Printf("未知事件: %s", env.Type)
	}
}

func (l *Loop) setRoster(r protocol.RosterPayload) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.roster = make(map[string]protocol.ServiceCard, len(r.Services))
	for _, c := range r.Services {
		l.roster[c.Name] = c
	}
}

// ---------- WS 服务端（接受 jump） ----------

var upgrader = websocket.Upgrader{
	CheckOrigin: func(*http.Request) bool { return true },
}

// outConn 是 agentloop 一侧的写封装（gorilla 不支持并发写）。
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

func (l *Loop) handleWS(w http.ResponseWriter, r *http.Request) {
	ws, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		l.logger.Printf("升级失败: %v", err)
		return
	}
	go l.serveConn(ws)
}

func (l *Loop) serveConn(ws *websocket.Conn) {
	c := &outConn{ws: ws}
	defer c.Close()
	for {
		_, data, err := ws.ReadMessage()
		if err != nil {
			return
		}
		env, err := protocol.Unmarshal(data)
		if err != nil {
			l.logger.Printf("坏帧: %v", err)
			continue
		}
		if env.Type != protocol.TypeJump {
			l.replyError(c, env, "unsupported message type: "+env.Type)
			continue
		}
		l.handleJump(c, env)
	}
}

func (l *Loop) handleJump(c *outConn, env protocol.Envelope) {
	var jp protocol.JumpPayload
	if err := env.DecodePayload(&jp); err != nil {
		l.replyError(c, env, "bad jump payload")
		return
	}
	fn, ok := l.actions[jp.Action]
	if !ok {
		l.replyError(c, env, "unknown action: "+jp.Action)
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	out, err := fn(ctx, env, jp)
	if err != nil {
		l.replyError(c, env, err.Error())
		return
	}
	data, err := protocol.EncodePayload(out)
	if err != nil {
		l.replyError(c, env, "encode result failed")
		return
	}
	resp, err := protocol.NewResponse(env, l.cfg.Name, protocol.ResponsePayload{OK: true, Data: data})
	if err == nil {
		_ = c.Send(resp)
	}
}

func (l *Loop) replyError(c *outConn, req protocol.Envelope, msg string) {
	resp, err := protocol.NewResponse(req, l.cfg.Name, protocol.ResponsePayload{OK: false, Error: msg})
	if err == nil {
		_ = c.Send(resp)
	}
}

// ---------- 内置动作（M1：测试 / 调试用） ----------

func (l *Loop) actionEcho(_ context.Context, _ protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var v any
	if err := protocol.DecodeRaw(in.Input, &v); err != nil {
		return nil, err
	}
	return map[string]any{"who": l.cfg.Name, "echo": v}, nil
}

// actionDebugJump 替调用方向目标服务发起一次跳转（调试 / 测试用），
// 支持 to = "self"（自我跳转）或服务名（查名册解析地址）。
func (l *Loop) actionDebugJump(ctx context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var req struct {
		To     string             `msgpack:"to"`
		Action string             `msgpack:"action"`
		Input  msgpack.RawMessage `msgpack:"input"`
	}
	if err := protocol.DecodeRaw(in.Input, &req); err != nil {
		return nil, err
	}
	if req.To == "" || req.Action == "" {
		return nil, errors.New("debug_jump: to 与 action 必填")
	}
	targetName, targetAddr, err := l.resolve(req.To)
	if err != nil {
		return nil, err
	}
	data, err := l.callService(ctx, targetName, targetAddr, req.Action, req.Input, env.Trace)
	if err != nil {
		return nil, err
	}
	if len(data) == 0 {
		return map[string]any{}, nil
	}
	return data, nil
}

// resolve 解析跳转目标：支持 "self" 与服务名（查名册）。
func (l *Loop) resolve(to string) (name, addr string, err error) {
	if to == "self" {
		return l.cfg.Name, l.selfURL, nil
	}
	l.mu.Lock()
	card, ok := l.roster[to]
	l.mu.Unlock()
	if !ok {
		return "", "", fmt.Errorf("未知目标服务: %s", to)
	}
	return card.Name, card.Addr, nil
}

// callService 访问目标服务。
// M1：每次短连接（用完即走）；连接时长自适应（热则保留、冷则回落）在后续批次实现。
func (l *Loop) callService(ctx context.Context, targetName, targetAddr, action string, input msgpack.RawMessage, trace string) (msgpack.RawMessage, error) {
	c, err := protocol.Dial(targetAddr, nil)
	if err != nil {
		return nil, fmt.Errorf("连接 %s 失败: %w", targetAddr, err)
	}
	defer c.Close()

	env, err := protocol.NewEnvelope(protocol.TypeJump, l.cfg.Name, targetName, trace, protocol.JumpPayload{Action: action, Input: input})
	if err != nil {
		return nil, err
	}
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
