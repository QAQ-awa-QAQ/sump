package protocol

import (
	"context"
	"errors"
	"sync"

	"github.com/gorilla/websocket"
)

// ErrConnClosed 表示连接已关闭。
var ErrConnClosed = errors.New("protocol: connection closed")

// Client 是一条 WS 客户端连接：请求-响应配对 + 事件回调。
//
// M1 最小实现：不做断线重连与连接时长自适应（后续批次实现）。
// 连接持有一条读循环 goroutine：response 按 id 派发给调用方，
// 其余消息（事件）交给 onEvent 回调。
type Client struct {
	conn    *websocket.Conn
	writeMu sync.Mutex // gorilla 不支持并发写，写侧统一加锁

	pendingMu sync.Mutex
	pending   map[string]chan Envelope

	onEvent func(Envelope)

	closed    chan struct{}
	closeOnce sync.Once
}

// Dial 建立到 addr 的连接并启动读循环；onEvent 可为 nil。
func Dial(addr string, onEvent func(Envelope)) (*Client, error) {
	conn, _, err := websocket.DefaultDialer.Dial(addr, nil)
	if err != nil {
		return nil, err
	}
	c := &Client{
		conn:    conn,
		pending: make(map[string]chan Envelope),
		onEvent: onEvent,
		closed:  make(chan struct{}),
	}
	go c.readLoop()
	return c, nil
}

// Send 发送一条消息，不等待回复（事件、响应或长耗时请求）。
func (c *Client) Send(env Envelope) error {
	data, err := Marshal(env)
	if err != nil {
		return err
	}
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	if err := c.conn.WriteMessage(websocket.BinaryMessage, data); err != nil {
		c.close()
		return err
	}
	return nil
}

// Call 发送请求并等待同 id 的 response，或 ctx 超时 / 连接关闭。
func (c *Client) Call(ctx context.Context, env Envelope) (Envelope, error) {
	ch := make(chan Envelope, 1)
	c.pendingMu.Lock()
	c.pending[env.ID] = ch
	c.pendingMu.Unlock()
	defer func() {
		c.pendingMu.Lock()
		delete(c.pending, env.ID)
		c.pendingMu.Unlock()
	}()

	if err := c.Send(env); err != nil {
		return Envelope{}, err
	}
	select {
	case resp := <-ch:
		return resp, nil
	case <-ctx.Done():
		return Envelope{}, ctx.Err()
	case <-c.closed:
		return Envelope{}, ErrConnClosed
	}
}

// Close 主动关闭连接。
func (c *Client) Close() error {
	c.close()
	return nil
}

func (c *Client) readLoop() {
	defer c.close()
	for {
		_, data, err := c.conn.ReadMessage()
		if err != nil {
			return
		}
		env, err := Unmarshal(data)
		if err != nil {
			continue // 坏帧跳过（M1 最小实现）
		}
		if env.Type == TypeResponse {
			c.pendingMu.Lock()
			ch := c.pending[env.ID]
			c.pendingMu.Unlock()
			if ch != nil {
				ch <- env
			}
			continue
		}
		if c.onEvent != nil {
			c.onEvent(env)
		}
	}
}

func (c *Client) close() {
	c.closeOnce.Do(func() {
		close(c.closed)
		_ = c.conn.Close()
	})
}
