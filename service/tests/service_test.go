// service 骨架测试：注册（声明心跳）→ 断线自动重连并重新注册 → 关停时告别（bye）。
package tests

import (
	"context"
	"log"
	"net"
	"net/http"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"github.com/QAQ-awa-QAQ/sump/protocol"
	"github.com/QAQ-awa-QAQ/sump/service"
)

// ---------- 设置中心替身 ----------

type stubConn struct {
	ws *websocket.Conn
	mu sync.Mutex
}

func (c *stubConn) send(env protocol.Envelope) {
	data, err := protocol.Marshal(env)
	if err != nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	_ = c.ws.WriteMessage(websocket.BinaryMessage, data)
}

type stubCenter struct {
	ln  net.Listener
	srv *http.Server

	mu    sync.Mutex
	regs  []protocol.RegisterPayload
	byes  int
	conns map[*stubConn]struct{}
}

var upgrader = websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}

func startStubCenter(t *testing.T) *stubCenter {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	sc := &stubCenter{ln: ln, conns: map[*stubConn]struct{}{}}
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", sc.handleWS)
	sc.srv = &http.Server{Handler: mux}
	go func() { _ = sc.srv.Serve(ln) }()
	t.Cleanup(func() { _ = sc.srv.Close() })
	return sc
}

func (sc *stubCenter) URL() string { return "ws://" + sc.ln.Addr().String() + "/ws" }

func (sc *stubCenter) handleWS(w http.ResponseWriter, r *http.Request) {
	ws, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	c := &stubConn{ws: ws}
	sc.mu.Lock()
	sc.conns[c] = struct{}{}
	sc.mu.Unlock()
	defer func() {
		sc.mu.Lock()
		delete(sc.conns, c)
		sc.mu.Unlock()
		_ = ws.Close()
	}()

	for {
		_, data, err := ws.ReadMessage()
		if err != nil {
			return
		}
		env, err := protocol.Unmarshal(data)
		if err != nil {
			continue
		}
		switch env.Type {
		case protocol.TypeRegister:
			var reg protocol.RegisterPayload
			if err := env.DecodePayload(&reg); err != nil {
				continue
			}
			sc.mu.Lock()
			sc.regs = append(sc.regs, reg)
			sc.mu.Unlock()
			roster := protocol.RosterPayload{
				Services: []protocol.ServiceCard{{Name: "stub-center", Addr: sc.URL()}},
				Revision: 1,
			}
			respData, _ := protocol.EncodePayload(roster)
			resp, _ := protocol.NewResponse(env, "stub-center", protocol.ResponsePayload{OK: true, Data: respData})
			c.send(resp)
		case protocol.TypeHeartbeat:
			var hb protocol.HeartbeatPayload
			_ = env.DecodePayload(&hb)
			if hb.Status == "bye" {
				sc.mu.Lock()
				sc.byes++
				sc.mu.Unlock()
			}
		}
	}
}

// Registers 返回已收到的注册快照。
func (sc *stubCenter) Registers() []protocol.RegisterPayload {
	sc.mu.Lock()
	defer sc.mu.Unlock()
	out := make([]protocol.RegisterPayload, len(sc.regs))
	copy(out, sc.regs)
	return out
}

// Byes 返回已收到的告别心跳数。
func (sc *stubCenter) Byes() int {
	sc.mu.Lock()
	defer sc.mu.Unlock()
	return sc.byes
}

// DropConnections 模拟链路断开（如设置中心侧关闭全部连接）。
func (sc *stubCenter) DropConnections() {
	sc.mu.Lock()
	targets := make([]*stubConn, 0, len(sc.conns))
	for c := range sc.conns {
		targets = append(targets, c)
	}
	sc.mu.Unlock()
	for _, c := range targets {
		_ = c.ws.Close()
	}
}

// ---------- 用例 ----------

// TestRegisterReconnectBye 验证骨架核心：注册（声明心跳）→ 断线自动重连并重新注册 → 关停时告别。
func TestRegisterReconnectBye(t *testing.T) {
	sc := startStubCenter(t)
	logger := log.New(os.Stdout, "[svc-test] ", log.LstdFlags)

	s := service.New(service.Config{
		Name:              "svc-t",
		Listen:            "127.0.0.1:0",
		Center:            sc.URL(),
		HeartbeatInterval: 100 * time.Millisecond,
		Description:       "骨架测试服务",
		Provides:          []protocol.Provide{{Action: "echo", Output: "原样返回"}},
		Logger:            logger,
	})
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := s.Start(ctx); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(s.Shutdown)

	regs := sc.Registers()
	if len(regs) != 1 {
		t.Fatalf("注册次数 = %d, want 1", len(regs))
	}
	if regs[0].Name != "svc-t" || regs[0].HeartbeatMS != 100 {
		t.Fatalf("注册名片不符: %+v", regs[0])
	}

	// 断线 → 应自动重连并重新注册
	sc.DropConnections()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) && len(sc.Registers()) < 2 {
		time.Sleep(50 * time.Millisecond)
	}
	if got := len(sc.Registers()); got < 2 {
		t.Fatalf("断线后应重新注册，实际注册次数 = %d", got)
	}

	// 关停 → 应发一条 bye（中心据此立即摘除名册）
	s.Shutdown()
	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) && sc.Byes() == 0 {
		time.Sleep(20 * time.Millisecond)
	}
	if sc.Byes() == 0 {
		t.Fatal("关停时应发送 bye 心跳")
	}
}
