package server

// reasoner 服务的核心：把单步推理相关动作注册到服务骨架（注册 / 心跳 /
// 名册 / 断线自愈 / 告别见 service 包）。按 DESIGN.md 的“自我跳转”设计：
// reasoner 不持有循环——它是单步推理器，每收到一次输入产出一次结果（下一步由跳转推进）。

import (
	"context"
	"errors"
	"log"
	"sync"
	"time"

	"github.com/vmihailenco/msgpack/v5"

	"github.com/QAQ-awa-QAQ/sump/protocol"
	"github.com/QAQ-awa-QAQ/sump/reasoner/llm"
	"github.com/QAQ-awa-QAQ/sump/service"
)

// Config 是 reasoner 的启动配置（引导只靠它：自己的名字/地址 + 设置中心地址）。
type Config struct {
	Name              string        // 服务名（注册用）
	Listen            string        // 监听地址 host:port
	Center            string        // 设置中心 WS 地址
	HeartbeatInterval time.Duration // 心跳间隔（默认 15s）
	Memory            string        // 记忆服务名（默认 memory——“完全启动”链的另一半）
	Images            string        // 图片服务名（默认 images——推理前取图内联）
	LLM               llm.Client    // 单步推理的 LLM 客户端（user_message / step 必需；nil 时相关动作报错）
	ToolConcurrency   int           // 单会话工具并发上限（默认 10；负值 = 不限制；同一服务可并发重复）
}

// Server 是 reasoner 服务实例（服务骨架 + 推理配置）。
type Server struct {
	*service.Service

	cfg    Config
	logger *log.Logger

	semsMu sync.Mutex               // 工具并发信号量表锁
	sems   map[string]chan struct{} // 会话 → 工具并发信号量（懒创建）
}

// New 创建实例并注册动作。
func New(cfg Config, logger *log.Logger) *Server {
	if cfg.Memory == "" {
		cfg.Memory = "memory"
	}
	if cfg.Images == "" {
		cfg.Images = "images"
	}
	if cfg.ToolConcurrency == 0 {
		cfg.ToolConcurrency = 10
	}
	s := &Server{cfg: cfg, logger: logger, sems: map[string]chan struct{}{}}
	s.Service = service.New(service.Config{
		Name:              cfg.Name,
		Listen:            cfg.Listen,
		Center:            cfg.Center,
		HeartbeatInterval: cfg.HeartbeatInterval,
		Description:       "LLM 单步推理：任务先经记忆服务托管，收到来自记忆的 resume 才完全启动（调 LLM API）",
		Provides: []protocol.Provide{
			{Action: "user_message", Input: "用户消息文本 {text}", Output: "受理回执（最终结果由 deliver 另行送达）"},
			{Action: "echo", Input: "任意", Output: "原样返回（测试用）"},
			{Action: "debug_jump", Input: "{to, action, input}", Output: "目标服务的响应数据（调试用）"},
		},
		Settings: []protocol.Setting{{Key: "conn.default_ttl", Default: "5m"}},
		Logger:   logger,
	})
	s.Handle("echo", s.actionEcho)
	s.Handle("debug_jump", s.actionDebugJump)
	s.Handle("user_message", s.actionUserMessage)
	s.Handle("step", s.actionStep)
	s.Handle("resume", s.actionResume)
	return s
}

// ---------- 调试 / 测试动作 ----------

func (s *Server) actionEcho(_ context.Context, _ protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var v any
	if err := protocol.DecodeRaw(in.Input, &v); err != nil {
		return nil, err
	}
	return map[string]any{"who": s.cfg.Name, "echo": v}, nil
}

// actionDebugJump 替调用方向目标服务发起一次跳转（调试 / 测试用），
// 支持 to = "self"（自我跳转）或服务名（查名册解析地址）。
func (s *Server) actionDebugJump(ctx context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error) {
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
	data, err := s.Call(ctx, req.To, req.Action, req.Input, env.Trace, "")
	if err != nil {
		return nil, err
	}
	if len(data) == 0 {
		return map[string]any{}, nil
	}
	return data, nil
}
