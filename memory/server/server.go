// memory 服务的核心：把记忆动作注册到服务骨架（注册 / 心跳 / 名册 /
// 断线自愈 / 告别见 service 包）。
// recall 收到 llm 托管的任务上下文 → 查会话历史并组装记忆 → 以 resume 发回 llm（触发其“完全启动”）。
package server

import (
	"context"
	"errors"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/QAQ-awa-QAQ/sump/memory/compose"
	"github.com/QAQ-awa-QAQ/sump/memory/store"
	"github.com/QAQ-awa-QAQ/sump/protocol"
	"github.com/QAQ-awa-QAQ/sump/service"
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

// Server 是 memory 服务实例（服务骨架 + 会话库）。
type Server struct {
	*service.Service

	cfg    Config
	logger *log.Logger
}

// New 创建实例并注册动作。
func New(cfg Config, logger *log.Logger) *Server {
	if cfg.HistoryLimit <= 0 {
		cfg.HistoryLimit = 12
	}
	s := &Server{cfg: cfg, logger: logger}
	s.Service = service.New(service.Config{
		Name:              cfg.Name,
		Listen:            cfg.Listen,
		Center:            cfg.Center,
		HeartbeatInterval: cfg.HeartbeatInterval,
		Description:       "记忆服务：会话历史存储与上下文组装（recall 后向 llm 回发 resume）",
		Provides: []protocol.Provide{
			{Action: "recall", Input: "任务上下文 {conversation_id, messages, boss}", Output: "受理回执；随后向调用方发送 resume（注入记忆后的上下文）"},
			{Action: "store", Input: "{conversation_id, role, content}", Output: "落库回执"},
		},
		Settings: []protocol.Setting{{Key: "conn.default_ttl", Default: "5m"}},
		Logger:   logger,
	})
	s.Handle("recall", s.actionRecall)
	s.Handle("store", s.actionStore)
	return s
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

	if err := s.fireResume(env, protocol.ResumePayload{Context: protocol.TaskContext{
		ConversationID: cid,
		Messages:       final,
		Boss:           tc.Boss,
	}}); err != nil {
		return nil, err
	}

	return map[string]any{"status": "accepted"}, nil
}

// fireResume 向调用方（llm 服务）发送组装完成的上下文——“过程中的 boss 是 llm”。
// resolve 失败会同步返回（调用方可收到错误）；投递本身异步进行（发出即完）。
func (s *Server) fireResume(req protocol.Envelope, payload any) error {
	target := req.From
	if target == "" {
		return errors.New("recall: 请求缺少 from，无法回发 resume")
	}
	if _, _, err := s.Resolve(target); err != nil {
		return err
	}
	s.Fire(target, "resume", payload, req.Trace, target)
	return nil
}
