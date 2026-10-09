package server

// 单步推理：roster → LLM 工具、工具调用执行、自跳（step）与交付（deliver）。
// 完全启动链：任务与自跳都先经记忆服务（recall 托管上下文）；只有“from=memory 的 resume”
// 才触发对 LLM API 的调用。循环不驻留本服务：每步“收到 → 处理 → 发出下一跳 → 结束”。

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"

	"github.com/vmihailenco/msgpack/v5"

	"github.com/QAQ-awa-QAQ/sump/protocol"
	"github.com/QAQ-awa-QAQ/sump/reasoner/llm"
)

// systemPrompt 是单步推理器的系统提示（M2 初版）。
const systemPrompt = `你是 SUMP 服务网络中的“单步推理器”（reasoner 服务）。
你会收到一段对话上下文。你的职责是决定下一步：
1. 需要外部能力时，调用提供的工具（工具 = 网络中其他服务的动作）；
2. 当任务可以收尾、或用户问候闲聊时，直接输出最终答复文本。
工具由系统代你执行，结果会以 tool 消息追加到对话中再交给你继续。`

// structuralActions 是不作为工具暴露给 LLM 的动作：协议/链机制动作（模型不得绕过链路），
// 以及本服务的调试/测试动作（echo / debug_jump——不给模型“万能遥控”）。
var structuralActions = map[string]bool{
	"user_message": true,
	"step":         true,
	"deliver":      true,
	"recall":       true, // memory 服务：记忆请求
	"store":        true, // memory 服务：对话落库
	"resume":       true, // 本服务的“完全启动”入口（仅接受 from=memory）
	"save":         true, // images 服务：保存图片（qq 侧调用）
	"fetch":        true, // images 服务：取图（llm 侧按需调用）
	"echo":         true, // 本服务：连通性测试（仅供直连调试）
	"debug_jump":   true, // 本服务：调试代理跳转
}

// rosterTools 把名册里各服务的 provides 映射为 LLM 工具。
func (s *Server) rosterTools() []llm.Tool {
	var out []llm.Tool
	for _, card := range s.Roster() {
		for _, p := range card.Provides {
			if structuralActions[p.Action] {
				continue
			}
			out = append(out, llm.Tool{
				Type: "function",
				Function: llm.ToolFunction{
					Name:        card.Name + "__" + p.Action,
					Description: fmt.Sprintf("服务 %s（%s）的动作 %s：输入 %s；输出 %s", card.Name, card.Description, p.Action, p.Input, p.Output),
					Parameters:  map[string]any{"type": "object"},
				},
			})
		}
	}
	return out
}

// parseToolName 解析“服务__动作”。
func parseToolName(name string) (service, action string, ok bool) {
	parts := strings.SplitN(name, "__", 2)
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return "", "", false
	}
	return parts[0], parts[1], true
}

// argsToRaw 把工具调用的 JSON 参数转为协议的 msgpack 输入。
func argsToRaw(args string) (msgpack.RawMessage, error) {
	if strings.TrimSpace(args) == "" {
		return nil, nil
	}
	var v any
	if err := json.Unmarshal([]byte(args), &v); err != nil {
		return nil, fmt.Errorf("参数不是合法 JSON: %w", err)
	}
	return protocol.EncodePayload(v)
}

// rawToJSONText 把 msgpack 原始数据转为 JSON 文本（给 LLM 阅读）。
func rawToJSONText(raw msgpack.RawMessage) string {
	if len(raw) == 0 {
		return "{}"
	}
	var v any
	if err := msgpack.Unmarshal(raw, &v); err != nil {
		return fmt.Sprintf("%v", []byte(raw))
	}
	b, err := json.Marshal(v)
	if err != nil {
		return fmt.Sprintf("%v", v)
	}
	return string(b)
}

// executeToolCall 执行一次工具调用：解析目标 → 跳转（短响应）→ 结果消息。
// 任何失败都转成 tool 消息内容（交回 LLM 决定），不中断链。
func (s *Server) executeToolCall(ctx context.Context, env protocol.Envelope, call llm.ToolCall) llm.Message {
	msg := llm.Message{Role: "tool", ToolCallID: call.ID}
	content, err := s.runToolCall(ctx, env, call)
	if err != nil {
		s.logger.Printf("工具 %s 失败: %v", call.Function.Name, err)
		msg.Content = "错误: " + err.Error()
		return msg
	}
	s.logger.Printf("工具 %s 完成: %.120s", call.Function.Name, content)
	msg.Content = content
	return msg
}

// runToolCall 执行工具调用并返回给 LLM 的内容文本（JSON）。
func (s *Server) runToolCall(ctx context.Context, env protocol.Envelope, call llm.ToolCall) (string, error) {
	svc, action, ok := parseToolName(call.Function.Name)
	if !ok {
		return "", fmt.Errorf("工具名无效: %s", call.Function.Name)
	}
	rawIn, err := argsToRaw(call.Function.Arguments)
	if err != nil {
		return "", err
	}
	data, err := s.Call(ctx, svc, action, rawIn, env.Trace, "")
	if err != nil {
		return "", err
	}
	return rawToJSONText(data), nil
}

// runToolCalls 并行执行多个工具调用，结果按调用顺序返回。
func (s *Server) runToolCalls(ctx context.Context, env protocol.Envelope, calls []llm.ToolCall) []llm.Message {
	results := make([]llm.Message, len(calls))
	var wg sync.WaitGroup
	for i, call := range calls {
		wg.Add(1)
		go func(i int, call llm.ToolCall) {
			defer wg.Done()
			results[i] = s.executeToolCall(ctx, env, call)
		}(i, call)
	}
	wg.Wait()
	return results
}

// resolveImages 取“最近一条带图消息”的图片数据（id → data URL），供 LLM 内联。
// 更早的图片引用保持文本占位（由 llm 序列化层处理）；失败仅记日志，不阻断推理。
func (s *Server) resolveImages(ctx context.Context, trace string, messages []llm.Message) map[string]string {
	var ids []string
	for i := len(messages) - 1; i >= 0; i-- {
		if len(messages[i].ImageIDs) > 0 {
			ids = messages[i].ImageIDs
			break
		}
	}
	if len(ids) == 0 {
		return nil
	}
	if _, _, err := s.Resolve(s.cfg.Images); err != nil {
		s.logger.Printf("取图失败（服务 %s）: %v", s.cfg.Images, err)
		return nil
	}
	out := make(map[string]string, len(ids))
	var mu sync.Mutex
	var wg sync.WaitGroup
	for _, id := range ids {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			data, err := s.Call(ctx, s.cfg.Images, "fetch", protocol.ImageFetchPayload{ID: id}, trace, "")
			if err != nil {
				s.logger.Printf("取图 %s 失败: %v", id, err)
				return
			}
			var fr protocol.ImageFetchResult
			if err := protocol.DecodeRaw(data, &fr); err != nil || fr.Data == "" {
				s.logger.Printf("取图 %s 结果无效", id)
				return
			}
			mu.Lock()
			out[id] = "data:" + fr.Mime + ";base64," + fr.Data
			mu.Unlock()
		}(id)
	}
	wg.Wait()
	if len(out) > 0 {
		s.logger.Printf("已取图 %d/%d 张（内联给模型）", len(out), len(ids))
	}
	return out
}

// stepPayload 是自跳（step）的 payload：完整消息历史随消息携带，会话标识随行。
type stepPayload struct {
	Messages       []llm.Message `msgpack:"messages"`
	ConversationID string        `msgpack:"conversation_id,omitempty"`
}

// fireStep 自跳：向后继推理发 step——发出即完，后台尽力送达（失败记日志）。
func (s *Server) fireStep(env protocol.Envelope, conversationID string, messages []llm.Message) {
	s.Fire("self", "step", stepPayload{Messages: messages, ConversationID: conversationID}, env.Trace, env.Boss)
}

// startMemoryRound 开启一轮“记忆往返”：把任务上下文（含原 boss）托管给记忆服务。
// 记忆服务的 resume（from=memory）回来时才真正调用 LLM API（完全启动）。
func (s *Server) startMemoryRound(env protocol.Envelope, conversationID string, messages []llm.Message) {
	s.Fire(s.cfg.Memory, "recall", protocol.RecallPayload{Context: protocol.TaskContext{
		ConversationID: conversationID,
		Messages:       messages,
		Boss:           env.Boss,
	}}, env.Trace, s.cfg.Name)
}

// deliverToBoss 把最终结果交付给 boss（同步等回执；失败返回错误）。
// 附带会话标识：boss 用它把结果路由回原会话（如 QQ 私聊）。
func (s *Server) deliverToBoss(ctx context.Context, env protocol.Envelope, conversationID, text string) error {
	if env.Boss == "" {
		return errors.New("无 boss，结果无法交付")
	}
	if _, err := s.Call(ctx, env.Boss, "deliver", protocol.DeliverPayload{Text: text, ConversationID: conversationID}, env.Trace, ""); err != nil {
		return fmt.Errorf("交付 boss(%s) 失败: %w", env.Boss, err)
	}
	return nil
}

// inferStep 是单步推理核心：一次 LLM 调用 → 决策（继续 / 收尾）。
// 只被完全启动链触发（actionResume → inferStep）。
func (s *Server) inferStep(ctx context.Context, env protocol.Envelope, conversationID string, messages []llm.Message) (any, error) {
	if s.cfg.LLM == nil {
		return nil, errors.New("LLM 未配置（-llm-key 或环境变量 DEEPSEEK_API_KEY）")
	}
	resp, err := s.cfg.LLM.Chat(ctx, llm.ChatRequest{
		Messages: messages,
		Tools:    s.rosterTools(),
		Images:   s.resolveImages(ctx, env.Trace, messages),
	})
	if err != nil {
		return nil, fmt.Errorf("LLM 调用失败: %w", err)
	}

	switch {
	case len(resp.ToolCalls) > 0:
		// 并行执行工具（短响应），再自跳继续推理（下一轮先经记忆）——发出即完。
		results := s.runToolCalls(ctx, env, resp.ToolCalls)
		messages = append(messages, llm.Message{Role: "assistant", Content: resp.Content, ToolCalls: resp.ToolCalls})
		messages = append(messages, results...)
		s.fireStep(env, conversationID, messages)
		return map[string]any{"status": "accepted"}, nil
	case strings.TrimSpace(resp.Content) != "":
		// 判定结束：直接交付 boss（不沿链回传）。
		if err := s.deliverToBoss(ctx, env, conversationID, resp.Content); err != nil {
			return nil, err
		}
		// 交付成功：把最终答复记入记忆（尽力送达）。
		s.Fire(s.cfg.Memory, "store", protocol.StorePayload{
			ConversationID: conversationID, Role: "assistant", Content: resp.Content,
		}, env.Trace, s.cfg.Name)
		return map[string]any{"status": "done"}, nil
	default:
		return nil, errors.New("LLM 返回为空（既无 tool_calls 也无内容）")
	}
}

// actionUserMessage 是链的入口：boss 发来用户消息。
// 半启动：把任务上下文托管给记忆服务（recall）——收到来自记忆的 resume 才完全启动。
func (s *Server) actionUserMessage(_ context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var p protocol.UserMessagePayload
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	if strings.TrimSpace(p.Text) == "" && len(p.Images) == 0 {
		return nil, errors.New("user_message: text 与 images 至少必填其一")
	}
	cid := p.ConversationID
	if cid == "" {
		cid = "default"
	}

	// 记一条用户消息（尽力送达；幂等与去重在记忆服务侧处理）。
	s.Fire(s.cfg.Memory, "store", protocol.StorePayload{
		ConversationID: cid, Role: "user", Content: p.Text,
	}, env.Trace, s.cfg.Name)

	messages := []llm.Message{
		{Role: "system", Content: systemPrompt},
		{Role: "user", Content: p.Text, ImageIDs: p.Images},
	}
	s.startMemoryRound(env, cid, messages)
	return map[string]any{"status": "accepted"}, nil
}

// actionStep 承接前一跳：继续推理前同样先经记忆（半启动）。
func (s *Server) actionStep(_ context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var p stepPayload
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	if len(p.Messages) == 0 {
		return nil, errors.New("step: messages 为空")
	}
	cid := p.ConversationID
	if cid == "" {
		cid = "default"
	}
	s.startMemoryRound(env, cid, p.Messages)
	return map[string]any{"status": "accepted"}, nil
}

// actionResume 是完全启动的唯一入口：仅接受来自记忆服务的 resume。
// 记忆组装好的上下文到达后，才调用 LLM API（见 DESIGN.md §3 记忆往返）。
func (s *Server) actionResume(ctx context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error) {
	if env.From != s.cfg.Memory {
		return nil, fmt.Errorf("resume 仅接受来自记忆服务（%s）的调用，拒绝来源 %q", s.cfg.Memory, env.From)
	}
	var p protocol.ResumePayload
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	tc := p.Context
	if len(tc.Messages) == 0 {
		return nil, errors.New("resume: 上下文为空")
	}
	// 该跳信封 boss 是 llm 自身（记忆为 llm 工作）；任务原 boss 随上下文恢复。
	taskEnv := env
	if tc.Boss != "" {
		taskEnv.Boss = tc.Boss
	}
	cid := tc.ConversationID
	if cid == "" {
		cid = "default"
	}
	return s.inferStep(ctx, taskEnv, cid, tc.Messages)
}
