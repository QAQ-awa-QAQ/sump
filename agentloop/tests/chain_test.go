package tests

// M3 全链测试（完全启动）：user_message → 记忆往返（recall → resume）→ 工具跳转（短响应）
// → 自跳(step) → 再来一轮记忆往返 → 交付(deliver) 直达 boss。

import (
	"context"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/QAQ-awa-QAQ/sump/agentloop/llm"
	"github.com/QAQ-awa-QAQ/sump/agentloop/loop"
	"github.com/QAQ-awa-QAQ/sump/protocol"
)

// stubBoss 是“老板”的最小替身：实现约定的 deliver 动作，收到结果放进 channel。
type stubBoss struct {
	ln        net.Listener
	srv       *http.Server
	delivered chan protocol.DeliverPayload
}

func startStubBoss(t *testing.T, center *stubCenter) *stubBoss {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	b := &stubBoss{ln: ln, delivered: make(chan protocol.DeliverPayload, 4)}
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", b.handleWS)
	b.srv = &http.Server{Handler: mux}
	go func() { _ = b.srv.Serve(ln) }()
	t.Cleanup(func() { _ = b.srv.Close() })

	// 把 boss 名片放进中心（agentloop 从 roster 解析它的地址）。
	center.mu.Lock()
	center.cards["stub-boss"] = protocol.ServiceCard{
		Name:        "stub-boss",
		Addr:        b.URL(),
		Description: "老板测试替身",
		Provides:    []protocol.Provide{{Action: "deliver", Input: "{text}", Output: "回执"}},
	}
	center.mu.Unlock()
	return b
}

func (b *stubBoss) URL() string { return "ws://" + b.ln.Addr().String() + "/ws" }

func (b *stubBoss) handleWS(w http.ResponseWriter, r *http.Request) {
	ws, err := stubUpgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	c := &stubConn{ws: ws}
	defer ws.Close()
	for {
		_, data, err := ws.ReadMessage()
		if err != nil {
			return
		}
		env, err := protocol.Unmarshal(data)
		if err != nil {
			continue
		}
		if env.Type != protocol.TypeJump {
			continue
		}
		var jp protocol.JumpPayload
		if err := env.DecodePayload(&jp); err != nil {
			continue
		}
		if jp.Action == "deliver" {
			var p protocol.DeliverPayload
			_ = protocol.DecodeRaw(jp.Input, &p)
			select {
			case b.delivered <- p:
			default:
			}
			resp, _ := protocol.NewResponse(env, "stub-boss", protocol.ResponsePayload{OK: true})
			c.send(resp)
		}
	}
}

// TestInferChain 验证 Fake LLM 驱动的全链：
// user_message（快速回执）→ LLM 决定调 echo（真跳转、短响应）→ 自跳 step
// → LLM 收尾输出文本 → deliver 直达 boss。
func TestInferChain(t *testing.T) {
	sc := startStubCenter(t)
	boss := startStubBoss(t, sc)
	mem := startStubMemory(t, sc)

	fake := &llm.Fake{Replies: []llm.Message{
		{Role: "assistant", ToolCalls: []llm.ToolCall{{
			ID: "call_1", Type: "function",
			Function: llm.FunctionCall{Name: "agentloop__echo", Arguments: `{"msg":"hi"}`},
		}}},
		{Role: "assistant", Content: "最终答复：你好！"},
	}}

	logger := log.New(os.Stdout, "[chain-test] ", log.LstdFlags)
	l := loop.New(loop.Config{
		Name:              "agentloop",
		Listen:            "127.0.0.1:0",
		Center:            sc.URL(),
		HeartbeatInterval: 100 * time.Millisecond,
		Memory:            "memory",
		LLM:               fake,
	}, logger)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := l.Start(ctx); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(l.Shutdown)
	mem.setAgentURL(l.WsURL())

	c := dialAgent(t, l)

	// 发起链：boss=stub-boss——“结果交付对象”。
	raw, err := protocol.EncodePayload(map[string]any{"text": "你好"})
	if err != nil {
		t.Fatal(err)
	}
	req, err := protocol.NewEnvelope(protocol.TypeJump, "test", "agentloop", "", protocol.JumpPayload{Action: "user_message", Input: raw})
	if err != nil {
		t.Fatal(err)
	}
	req.Boss = "stub-boss"
	resp, err := c.Call(ctx, req)
	if err != nil {
		t.Fatal(err)
	}
	var ack protocol.ResponsePayload
	if err := resp.DecodePayload(&ack); err != nil {
		t.Fatal(err)
	}
	if !ack.OK {
		t.Fatalf("user_message 未被受理: %s", ack.Error)
	}

	// 等待 boss 收到 deliver（链在后台推进）。
	select {
	case d := <-boss.delivered:
		if d.Text != "最终答复：你好！" {
			t.Fatalf("交付内容不符: %q", d.Text)
		}
		if d.ConversationID != "default" {
			t.Fatalf("交付应带回会话标识: %q", d.ConversationID)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("超时：boss 未收到 deliver")
	}

	// 校验链路确实经过了“工具跳转 + 自跳”：Fake 收到两次请求。
	if fake.CallCount() != 2 {
		t.Fatalf("Fake LLM 调用次数 = %d, want 2", fake.CallCount())
	}
	first := fake.Requests[0]
	foundEchoTool := false
	for _, tool := range first.Tools {
		if tool.Function.Name == "agentloop__echo" {
			foundEchoTool = true
		}
	}
	if !foundEchoTool {
		t.Fatalf("第一轮请求应包含 agentloop__echo 工具: %+v", first.Tools)
	}
	// 完全启动链：请求必须携带记忆块（由 resume 注入）。
	if !hasMemoryBlock(first.Messages) {
		t.Fatalf("第一轮请求应含记忆块: %+v", first.Messages)
	}
	second := fake.Requests[1]
	hasToolResult := false
	for _, m := range second.Messages {
		if strings.Contains(m.Content, "错误") {
			t.Fatalf("工具执行出错: %s", m.Content)
		}
		if m.Role == "tool" && strings.Contains(m.Content, "hi") {
			hasToolResult = true
		}
	}
	if !hasToolResult {
		t.Fatalf("第二轮请求应包含 echo 的 tool 结果: %+v", second.Messages)
	}
	if !hasMemoryBlock(second.Messages) {
		t.Fatalf("第二轮请求应含记忆块: %+v", second.Messages)
	}

	// 记忆写入：用户消息（链入口）与最终答复（交付后）各记一条。
	stores := waitStores(t, mem, 2, 5*time.Second)
	var gotUser, gotAssistant bool
	for _, s := range stores {
		if s.Role == "user" && s.Content == "你好" {
			gotUser = true
		}
		if s.Role == "assistant" && s.Content == "最终答复：你好！" {
			gotAssistant = true
		}
	}
	if !gotUser || !gotAssistant {
		t.Fatalf("store 内容不符: %+v", stores)
	}
}

// hasMemoryBlock 判断消息链里是否有记忆块。
func hasMemoryBlock(messages []llm.Message) bool {
	for _, m := range messages {
		if m.Role == "system" && strings.HasPrefix(m.Content, "【记忆】") {
			return true
		}
	}
	return false
}

// waitStores 等待记忆替身收到至少 n 条 store。
func waitStores(t *testing.T, m *stubMemory, n int, timeout time.Duration) []protocol.StorePayload {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if s := m.Stores(); len(s) >= n {
			return s
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("等待 %d 条 store 超时（实际 %d）", n, len(m.Stores()))
	return nil
}

// TestResumeRejected 验证“完全启动”入口只接受 from=memory——其他来源一律拒绝。
func TestResumeRejected(t *testing.T) {
	sc := startStubCenter(t)
	l := startAgent(t, sc.URL())

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	c := dialAgent(t, l)

	rp := jump(t, c, "resume", protocol.ResumePayload{Context: protocol.TaskContext{
		Messages: []llm.Message{{Role: "user", Content: "x"}},
	}}, ctx)
	if rp.OK {
		t.Fatal("resume 应拒绝非记忆来源的调用")
	}
	if !strings.Contains(rp.Error, "仅接受来自记忆服务") {
		t.Fatalf("错误信息不符: %s", rp.Error)
	}
}
