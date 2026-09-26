package protocol

import (
	"testing"
)

// TestTaskContextRoundTrip 验证记忆往返上下文（含工具调用链）的编解码保真。
func TestTaskContextRoundTrip(t *testing.T) {
	in := RecallPayload{Context: TaskContext{
		ConversationID: "conv-1",
		Boss:           "qq",
		Messages: []Message{
			{Role: "system", Content: "sys"},
			{Role: "user", Content: "你好"},
			{Role: "assistant", ToolCalls: []ToolCall{{
				ID: "c1", Type: "function",
				Function: FunctionCall{Name: "svc__act", Arguments: `{"a":1}`},
			}}},
			{Role: "tool", Content: `{"ok":true}`, ToolCallID: "c1"},
		},
	}}
	env, err := NewEnvelope(TypeJump, "agentloop", "memory", "trace-1", in)
	if err != nil {
		t.Fatal(err)
	}
	data, err := Marshal(env)
	if err != nil {
		t.Fatal(err)
	}
	got, err := Unmarshal(data)
	if err != nil {
		t.Fatal(err)
	}
	var out RecallPayload
	if err := got.DecodePayload(&out); err != nil {
		t.Fatal(err)
	}
	if out.Context.ConversationID != in.Context.ConversationID || out.Context.Boss != in.Context.Boss {
		t.Fatalf("上下文头不符: %+v", out.Context)
	}
	if len(out.Context.Messages) != len(in.Context.Messages) {
		t.Fatalf("消息条数不符: %d != %d", len(out.Context.Messages), len(in.Context.Messages))
	}
	m := out.Context.Messages[2]
	if m.Role != "assistant" || len(m.ToolCalls) != 1 || m.ToolCalls[0].Function.Name != "svc__act" || m.ToolCalls[0].Function.Arguments != `{"a":1}` {
		t.Fatalf("工具调用消息不符: %+v", m)
	}
	if out.Context.Messages[3].ToolCallID != "c1" {
		t.Fatalf("tool_call_id 丢失: %+v", out.Context.Messages[3])
	}

	// Resume 与 Store 同构走一遍。
	rp := ResumePayload{Context: out.Context}
	if _, err := NewEnvelope(TypeJump, "memory", "agentloop", "trace-1", rp); err != nil {
		t.Fatal(err)
	}
	if _, err := NewEnvelope(TypeJump, "agentloop", "memory", "trace-1", StorePayload{ConversationID: "conv-1", Role: "user", Content: "你好"}); err != nil {
		t.Fatal(err)
	}
}
