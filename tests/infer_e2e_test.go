package tests

// M3：假 DeepSeek 驱动的真进程端到端——settings-center + agentloop + memory + 假 boss。
// 零外网依赖：LLM 由本进程内的 OpenAI 兼容替身扮演；验证完全启动链与记忆注入。

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"github.com/QAQ-awa-QAQ/sump/protocol"
)

// fakeDeepSeek 是 OpenAI 兼容的假 LLM：toolFirst=true 时第一次请求回 tool_call、之后回文本；
// toolFirst=false 时始终回文本。
type fakeDeepSeek struct {
	mu       sync.Mutex
	calls    int
	requests []map[string]any
	srv      *httptest.Server
}

func startFakeDeepSeek(t *testing.T, toolFirst bool) *fakeDeepSeek {
	t.Helper()
	f := &fakeDeepSeek{}
	f.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/chat/completions") {
			http.NotFound(w, r)
			return
		}
		body, _ := io.ReadAll(r.Body)
		var req map[string]any
		_ = json.Unmarshal(body, &req)

		f.mu.Lock()
		f.calls++
		f.requests = append(f.requests, req)
		call := f.calls
		f.mu.Unlock()

		var msg map[string]any
		if toolFirst && call == 1 {
			msg = map[string]any{
				"role": "assistant",
				"tool_calls": []any{map[string]any{
					"id":   "call_e2e",
					"type": "function",
					"function": map[string]any{
						"name":      "agentloop__echo",
						"arguments": `{"msg":"e2e"}`,
					},
				}},
			}
		} else {
			msg = map[string]any{"role": "assistant", "content": "E2E 最终答复"}
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"choices": []any{map[string]any{"message": msg}}})
	}))
	t.Cleanup(f.srv.Close)
	return f
}

func (f *fakeDeepSeek) URL() string { return f.srv.URL }

func (f *fakeDeepSeek) Calls() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.calls
}

func (f *fakeDeepSeek) Requests() []map[string]any {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]map[string]any, len(f.requests))
	copy(out, f.requests)
	return out
}

// bossConn 是 e2eBoss 一侧的写封装。
type bossConn struct {
	ws *websocket.Conn
	mu sync.Mutex
}

func (c *bossConn) send(env protocol.Envelope) {
	data, err := protocol.Marshal(env)
	if err != nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	_ = c.ws.WriteMessage(websocket.BinaryMessage, data)
}

// e2eBoss 是测试进程内的“老板”替身：实现约定的 deliver 动作。
type e2eBoss struct {
	ln        net.Listener
	srv       *http.Server
	delivered chan string
}

var bossUpgrader = websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}

func startE2EBoss(t *testing.T) *e2eBoss {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	b := &e2eBoss{ln: ln, delivered: make(chan string, 4)}
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", b.handleWS)
	b.srv = &http.Server{Handler: mux}
	go func() { _ = b.srv.Serve(ln) }()
	t.Cleanup(func() { _ = b.srv.Close() })
	return b
}

func (b *e2eBoss) URL() string { return "ws://" + b.ln.Addr().String() + "/ws" }

func (b *e2eBoss) handleWS(w http.ResponseWriter, r *http.Request) {
	ws, err := bossUpgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	c := &bossConn{ws: ws}
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
			var p struct {
				Text string `msgpack:"text"`
			}
			_ = protocol.DecodeRaw(jp.Input, &p)
			select {
			case b.delivered <- p.Text:
			default:
			}
			resp, _ := protocol.NewResponse(env, "e2e-boss", protocol.ResponsePayload{OK: true})
			c.send(resp)
		}
	}
}

// register 把 boss 名片注册进真设置中心（保持连接，接收 roster）。
func (b *e2eBoss) register(t *testing.T, centerURL string) *protocol.Client {
	t.Helper()
	c, err := protocol.Dial(centerURL, nil)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	env, err := protocol.NewEnvelope(protocol.TypeRegister, "e2e-boss", "settings-center", "", protocol.RegisterPayload{
		Name:        "e2e-boss",
		Addr:        b.URL(),
		Description: "e2e 老板替身",
		Provides:    []protocol.Provide{{Action: "deliver", Input: "{text}", Output: "回执"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	resp, err := c.Call(ctx, env)
	if err != nil {
		t.Fatal(err)
	}
	var rp protocol.ResponsePayload
	if err := resp.DecodePayload(&rp); err != nil {
		t.Fatal(err)
	}
	if !rp.OK {
		t.Fatalf("boss 注册失败: %s", rp.Error)
	}
	return c
}

// TestInferChainE2E 真进程版全链（完全启动）：user_message → 记忆往返（recall → resume）
// → 工具跳转 → 自跳 → 记忆往返 → deliver；并以预置会话历史验证记忆注入。
func TestInferChainE2E(t *testing.T) {
	scBin := buildService(t, "github.com/QAQ-awa-QAQ/sump/settings-center")
	alBin := buildService(t, "github.com/QAQ-awa-QAQ/sump/agentloop")
	memBin := buildService(t, "github.com/QAQ-awa-QAQ/sump/memory")

	fakeLLM := startFakeDeepSeek(t, true)
	boss := startE2EBoss(t)

	scPort := freePort(t)
	alPort := freePort(t)
	memPort := freePort(t)
	centerURL := fmt.Sprintf("ws://127.0.0.1:%d/ws", scPort)
	agentURL := fmt.Sprintf("ws://127.0.0.1:%d/ws", alPort)
	memoryURL := fmt.Sprintf("ws://127.0.0.1:%d/ws", memPort)

	startProc(t, scBin, "-addr", fmt.Sprintf("127.0.0.1:%d", scPort))
	waitWSReady(t, centerURL, 60*time.Second)

	// memory 先启动（agentloop 需要从名册解析到它）。
	startProc(t, memBin,
		"-addr", fmt.Sprintf("127.0.0.1:%d", memPort),
		"-center", centerURL,
		"-db", filepath.Join(t.TempDir(), "memory.db"),
	)
	waitWSReady(t, memoryURL, 60*time.Second)

	// boss 先进名册，再启动 agentloop。
	bossClient := boss.register(t, centerURL)
	t.Cleanup(func() { _ = bossClient.Close() })

	startProc(t, alBin,
		"-addr", fmt.Sprintf("127.0.0.1:%d", alPort),
		"-center", centerURL,
		"-llm-base", fakeLLM.URL(),
		"-llm-key", "test-key",
		"-llm-model", "fake-model",
	)
	waitWSReady(t, agentURL, 60*time.Second)

	// 等名册齐全。
	obs, err := protocol.Dial(centerURL, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = obs.Close() })
	waitRosterHas(t, obs, "agentloop", 60*time.Second)
	waitRosterHas(t, obs, "memory", 10*time.Second)

	// 预置会话历史（上一轮的对话）——验证 recall 会把它注入 LLM 请求。
	mc, err := protocol.Dial(memoryURL, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = mc.Close() })
	ctx0, cancel0 := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel0()
	for _, sp := range []protocol.StorePayload{
		{ConversationID: "e2e-conv", Role: "user", Content: "上次谈话内容A"},
		{ConversationID: "e2e-conv", Role: "assistant", Content: "上次答复B"},
	} {
		raw, err := protocol.EncodePayload(sp)
		if err != nil {
			t.Fatal(err)
		}
		env, err := protocol.NewEnvelope(protocol.TypeJump, "e2e", "memory", "", protocol.JumpPayload{Action: "store", Input: raw})
		if err != nil {
			t.Fatal(err)
		}
		resp, err := mc.Call(ctx0, env)
		if err != nil {
			t.Fatal(err)
		}
		var rp protocol.ResponsePayload
		if err := resp.DecodePayload(&rp); err != nil {
			t.Fatal(err)
		}
		if !rp.OK {
			t.Fatalf("预置 store 失败: %s", rp.Error)
		}
	}

	// 发起链：boss=e2e-boss。
	ac, err := protocol.Dial(agentURL, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ac.Close() })

	raw, err := protocol.EncodePayload(map[string]any{"text": "你好", "conversation_id": "e2e-conv"})
	if err != nil {
		t.Fatal(err)
	}
	req, err := protocol.NewEnvelope(protocol.TypeJump, "e2e", "agentloop", "", protocol.JumpPayload{Action: "user_message", Input: raw})
	if err != nil {
		t.Fatal(err)
	}
	req.Boss = "e2e-boss"

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	resp, err := ac.Call(ctx, req)
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

	select {
	case text := <-boss.delivered:
		if text != "E2E 最终答复" {
			t.Fatalf("交付文本不符: %q", text)
		}
	case <-time.After(30 * time.Second):
		t.Fatal("超时：boss 未收到 deliver")
	}

	if fakeLLM.Calls() != 2 {
		t.Fatalf("假 DeepSeek 调用次数 = %d, want 2", fakeLLM.Calls())
	}
	reqs := fakeLLM.Requests()

	// 第一轮请求：记忆块（预置会话历史）已被注入。
	msgs1, _ := reqs[0]["messages"].([]any)
	foundMemory := false
	for _, m := range msgs1 {
		mm, _ := m.(map[string]any)
		if s, _ := mm["content"].(string); strings.Contains(s, "【记忆】") && strings.Contains(s, "上次谈话内容A") {
			foundMemory = true
		}
	}
	if !foundMemory {
		t.Fatalf("第一轮 LLM 请求应含注入的会话历史: %+v", msgs1)
	}

	// 第二轮请求：含 echo 的 tool 结果（自跳轮同样先经记忆）。
	msgs2, _ := reqs[1]["messages"].([]any)
	found := false
	for _, m := range msgs2 {
		mm, _ := m.(map[string]any)
		if mm["role"] == "tool" {
			if s, _ := mm["content"].(string); strings.Contains(s, "e2e") {
				found = true
			}
		}
	}
	if !found {
		t.Fatalf("第二次 LLM 请求应包含 echo 的 tool 结果: %+v", msgs2)
	}
}
