package loop

// 单步推理：roster → LLM 工具、工具调用执行、自跳（step）与交付（deliver）。
// 循环不驻留本服务：每步“收到 → 处理 → 发出下一跳 → 结束”，
// 结果由链终点直接交付 boss（见 DESIGN.md §3 智能体循环）。

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/vmihailenco/msgpack/v5"

	"github.com/QAQ-awa-QAQ/sump/agentloop/llm"
	"github.com/QAQ-awa-QAQ/sump/protocol"
)

// systemPrompt 是单步推理器的系统提示（M2 初版）。
const systemPrompt = `你是 SUMP 服务网络中的“单步推理器”（agentloop 服务）。
你会收到一段对话上下文。你的职责是决定下一步：
1. 需要外部能力时，调用提供的工具（工具 = 网络中其他服务的动作）；
2. 当任务可以收尾、或用户问候闲聊时，直接输出最终答复文本。
工具由系统代你执行，结果会以 tool 消息追加到对话中再交给你继续。`

// structuralActions 是协议结构性动作：不作为工具暴露给 LLM。
var structuralActions = map[string]bool{
	"user_message": true,
	"step":         true,
	"deliver":      true,
}

// rosterTools 把名册里各服务的 provides 映射为 LLM 工具。
func (l *Loop) rosterTools() []llm.Tool {
	var out []llm.Tool
	for _, card := range l.Roster() {
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
func (l *Loop) executeToolCall(ctx context.Context, env protocol.Envelope, call llm.ToolCall) llm.Message {
	msg := llm.Message{Role: "tool", ToolCallID: call.ID}
	svc, action, ok := parseToolName(call.Function.Name)
	if !ok {
		msg.Content = "错误: 工具名无效: " + call.Function.Name
		return msg
	}
	targetName, targetAddr, err := l.resolve(svc)
	if err == nil {
		var rawIn msgpack.RawMessage
		rawIn, err = argsToRaw(call.Function.Arguments)
		if err == nil {
			var data msgpack.RawMessage
			data, err = l.callService(ctx, targetName, targetAddr, action, rawIn, env.Trace)
			if err == nil {
				msg.Content = rawToJSONText(data)
				return msg
			}
		}
	}
	msg.Content = "错误: " + err.Error()
	return msg
}

// runToolCalls 并行执行多个工具调用，结果按调用顺序返回。
func (l *Loop) runToolCalls(ctx context.Context, env protocol.Envelope, calls []llm.ToolCall) []llm.Message {
	results := make([]llm.Message, len(calls))
	var wg sync.WaitGroup
	for i, call := range calls {
		wg.Add(1)
		go func(i int, call llm.ToolCall) {
			defer wg.Done()
			results[i] = l.executeToolCall(ctx, env, call)
		}(i, call)
	}
	wg.Wait()
	return results
}

// stepPayload 是自跳（step）的 payload：完整消息历史随消息携带。
type stepPayload struct {
	Messages []llm.Message `msgpack:"messages"`
}

// fireStep 自跳：向后继推理发 step——发出即完，后台尽力送达（M2 无重试，失败记日志）。
func (l *Loop) fireStep(env protocol.Envelope, messages []llm.Message) {
	raw, err := protocol.EncodePayload(stepPayload{Messages: messages})
	if err != nil {
		l.logger.Printf("step 编码失败: %v", err)
		return
	}
	l.fireJump(l.cfg.Name, l.selfURL, "step", raw, env.Trace, env.Boss)
}

// fireJump 后台发起一跳（不等最终结果；完成与否仅记日志）。
func (l *Loop) fireJump(targetName, targetAddr, action string, input msgpack.RawMessage, trace, boss string) {
	go func() {
		c, err := protocol.Dial(targetAddr, nil)
		if err != nil {
			l.logger.Printf("fireJump 连接 %s 失败: %v", targetAddr, err)
			return
		}
		defer c.Close()
		env, err := protocol.NewEnvelope(protocol.TypeJump, l.cfg.Name, targetName, trace, protocol.JumpPayload{Action: action, Input: input})
		if err != nil {
			l.logger.Printf("fireJump 构造失败: %v", err)
			return
		}
		env.Boss = boss
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()
		if _, err := c.Call(ctx, env); err != nil {
			l.logger.Printf("fireJump %s(%s) 未确认送达: %v", targetName, action, err)
		}
	}()
}

// deliverToBoss 把最终结果交付给 boss（同步等回执；失败返回错误）。
func (l *Loop) deliverToBoss(ctx context.Context, env protocol.Envelope, text string) error {
	if env.Boss == "" {
		return errors.New("无 boss，结果无法交付")
	}
	targetName, targetAddr, err := l.resolve(env.Boss)
	if err != nil {
		return err
	}
	data, err := protocol.EncodePayload(map[string]any{"text": text})
	if err != nil {
		return err
	}
	if _, err := l.callService(ctx, targetName, targetAddr, "deliver", data, env.Trace); err != nil {
		return fmt.Errorf("交付 boss(%s) 失败: %w", env.Boss, err)
	}
	return nil
}

// inferStep 是单步推理核心：一次 LLM 调用 → 决策（继续 / 收尾）。
func (l *Loop) inferStep(ctx context.Context, env protocol.Envelope, messages []llm.Message) (any, error) {
	if l.cfg.LLM == nil {
		return nil, errors.New("LLM 未配置（-llm-key 或环境变量 DEEPSEEK_API_KEY）")
	}
	resp, err := l.cfg.LLM.Chat(ctx, llm.ChatRequest{Messages: messages, Tools: l.rosterTools()})
	if err != nil {
		return nil, fmt.Errorf("LLM 调用失败: %w", err)
	}

	switch {
	case len(resp.ToolCalls) > 0:
		// 并行执行工具（短响应），再自跳继续推理——发出即完。
		results := l.runToolCalls(ctx, env, resp.ToolCalls)
		messages = append(messages, llm.Message{Role: "assistant", Content: resp.Content, ToolCalls: resp.ToolCalls})
		messages = append(messages, results...)
		l.fireStep(env, messages)
		return map[string]any{"status": "accepted"}, nil
	case strings.TrimSpace(resp.Content) != "":
		// 判定结束：直接交付 boss（不沿链回传）。
		if err := l.deliverToBoss(ctx, env, resp.Content); err != nil {
			return nil, err
		}
		return map[string]any{"status": "done"}, nil
	default:
		return nil, errors.New("LLM 返回为空（既无 tool_calls 也无内容）")
	}
}

// actionUserMessage 是链的入口：boss 发来用户消息。
func (l *Loop) actionUserMessage(ctx context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var p struct {
		Text string `msgpack:"text"`
	}
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	if strings.TrimSpace(p.Text) == "" {
		return nil, errors.New("user_message: text 必填")
	}
	messages := []llm.Message{
		{Role: "system", Content: systemPrompt},
		{Role: "user", Content: p.Text},
	}
	return l.inferStep(ctx, env, messages)
}

// actionStep 承接前一跳：继续推理（消息历史随消息携带，完整显式）。
func (l *Loop) actionStep(ctx context.Context, env protocol.Envelope, in protocol.JumpPayload) (any, error) {
	var p stepPayload
	if err := protocol.DecodeRaw(in.Input, &p); err != nil {
		return nil, err
	}
	if len(p.Messages) == 0 {
		return nil, errors.New("step: messages 为空")
	}
	return l.inferStep(ctx, env, p.Messages)
}
