// Package hub 是设置中心的核心：服务注册表、全局清单与广播。
package hub

import (
	"log"
	"sort"
	"sync"
	"time"

	"github.com/QAQ-awa-QAQ/sump/protocol"
)

// Conn 是 hub 对一条已连接服务的抽象。
type Conn interface {
	Send(protocol.Envelope) error
	Close() error
}

// Hub 维护已注册服务的名片、连接与心跳时间。
type Hub struct {
	mu       sync.Mutex
	cards    map[string]protocol.ServiceCard
	conns    map[string]Conn
	lastSeen map[string]time.Time
	revision int64
	log      *log.Logger
}

// New 创建空的 Hub。
func New(logger *log.Logger) *Hub {
	return &Hub{
		cards:    make(map[string]protocol.ServiceCard),
		conns:    make(map[string]Conn),
		lastSeen: make(map[string]time.Time),
		log:      logger,
	}
}

// Register 记录 / 更新一个服务的名片与连接并推进 revision，返回最新快照。
func (h *Hub) Register(card protocol.ServiceCard, conn Conn) protocol.RosterPayload {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.cards[card.Name] = card
	h.conns[card.Name] = conn
	h.lastSeen[card.Name] = time.Now()
	h.revision++
	return h.snapshotLocked()
}

// PutSelf 把设置中心自身作为一张名片放进名册（无连接、仅信息），
// 使各服务可以访问设置中心（如 jump ping）。
func (h *Hub) PutSelf(card protocol.ServiceCard) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.cards[card.Name] = card
	h.revision++
}

// Disconnect 处理连接断开：仅移除连接映射，不视为离线
// （离线判定由心跳超时负责——适配“默认短连接”的连接模型）。
func (h *Hub) Disconnect(name string, conn Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if cur, ok := h.conns[name]; ok && cur == conn {
		delete(h.conns, name)
	}
}

// NoteSeen 记录一次心跳（离线检测在后续批次实现）。
func (h *Hub) NoteSeen(name string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.lastSeen[name] = time.Now()
}

// Snapshot 返回当前清单。
func (h *Hub) Snapshot() protocol.RosterPayload {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.snapshotLocked()
}

// Broadcast 把快照作为 roster 事件推给所有已注册连接（锁外发送，避免 IO 持锁）。
func (h *Hub) Broadcast(roster protocol.RosterPayload) {
	type target struct {
		name string
		conn Conn
	}
	h.mu.Lock()
	targets := make([]target, 0, len(h.conns))
	for name, c := range h.conns {
		targets = append(targets, target{name: name, conn: c})
	}
	h.mu.Unlock()

	for _, t := range targets {
		env, err := protocol.NewEnvelope(protocol.TypeRoster, "settings-center", t.name, "", roster)
		if err != nil {
			continue
		}
		if err := t.conn.Send(env); err != nil {
			h.log.Printf("roster 推送失败 (%s): %v", t.name, err)
		}
	}
}

func (h *Hub) snapshotLocked() protocol.RosterPayload {
	names := make([]string, 0, len(h.cards))
	for n := range h.cards {
		names = append(names, n)
	}
	sort.Strings(names)
	services := make([]protocol.ServiceCard, 0, len(names))
	for _, n := range names {
		services = append(services, h.cards[n])
	}
	return protocol.RosterPayload{Services: services, Revision: h.revision}
}
