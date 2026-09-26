package llm

// llm 包的单个文件测试：HTTP 客户端（httptest 冒充 DeepSeek）与 Fake 的行为。

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestChatParsesToolCalls(t *testing.T) {
	var gotAuth, gotPath string
	var gotReq ChatRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		gotPath = r.URL.Path
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &gotReq)

		_ = json.NewEncoder(w).Encode(map[string]any{
			"choices": []any{map[string]any{
				"message": map[string]any{
					"role": "assistant",
					"tool_calls": []any{map[string]any{
						"id":   "call_1",
						"type": "function",
						"function": map[string]any{
							"name":      "echo__echo",
							"arguments": `{"input":{"msg":"hi"}}`,
						},
					}},
				},
			}},
		})
	}))
	defer srv.Close()

	c := NewDeepSeekClient(srv.URL, "test-key", "deepseek-chat")
	msg, err := c.Chat(context.Background(), ChatRequest{
		Messages: []Message{{Role: "user", Content: "hello"}},
		Tools: []Tool{{
			Type:     "function",
			Function: ToolFunction{Name: "echo__echo", Description: "echo 测试动作", Parameters: map[string]any{"type": "object"}},
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if gotAuth != "Bearer test-key" {
		t.Fatalf("Authorization 头不符: %q", gotAuth)
	}
	if !strings.HasSuffix(gotPath, "/chat/completions") {
		t.Fatalf("请求路径不符: %q", gotPath)
	}
	if gotReq.Model != "deepseek-chat" {
		t.Fatalf("model 不符: %q", gotReq.Model)
	}
	if len(gotReq.Tools) != 1 || gotReq.Tools[0].Function.Name != "echo__echo" {
		t.Fatalf("tools 不符: %+v", gotReq.Tools)
	}
	if len(msg.ToolCalls) != 1 || msg.ToolCalls[0].Function.Name != "echo__echo" {
		t.Fatalf("解析 tool_calls 失败: %+v", msg)
	}
	if msg.ToolCalls[0].Function.Arguments != `{"input":{"msg":"hi"}}` {
		t.Fatalf("arguments 不符: %q", msg.ToolCalls[0].Function.Arguments)
	}
}

func TestChatErrorStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]any{"message": "invalid api key"}})
	}))
	defer srv.Close()

	c := NewDeepSeekClient(srv.URL, "bad", "deepseek-chat")
	_, err := c.Chat(context.Background(), ChatRequest{Messages: []Message{{Role: "user", Content: "x"}}})
	if err == nil || !strings.Contains(err.Error(), "invalid api key") {
		t.Fatalf("期望错误包含 invalid api key，实际: %v", err)
	}
}

func TestFakeSequence(t *testing.T) {
	f := &Fake{Replies: []Message{
		{Role: "assistant", ToolCalls: []ToolCall{{ID: "1", Type: "function", Function: FunctionCall{Name: "a", Arguments: "{}"}}}},
		{Role: "assistant", Content: "done"},
	}}
	ctx := context.Background()

	m1, _ := f.Chat(ctx, ChatRequest{})
	if len(m1.ToolCalls) != 1 || m1.ToolCalls[0].Function.Name != "a" {
		t.Fatalf("第 1 次应返回 tool_call: %+v", m1)
	}
	m2, _ := f.Chat(ctx, ChatRequest{})
	if m2.Content != "done" {
		t.Fatalf("第 2 次应返回文本: %+v", m2)
	}
	m3, _ := f.Chat(ctx, ChatRequest{})
	if m3.Content != "done" {
		t.Fatalf("第 3 次应重复最后一条: %+v", m3)
	}
	if f.CallCount() != 3 {
		t.Fatalf("CallCount = %d", f.CallCount())
	}
}
