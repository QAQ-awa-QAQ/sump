package protocol

import "github.com/vmihailenco/msgpack/v5"

// Provide 描述服务对外提供的一个动作（“接受什么输入、有什么输出”）。
type Provide struct {
	Action string `msgpack:"action"`
	Input  string `msgpack:"input,omitempty"`
	Output string `msgpack:"output,omitempty"`
}

// Setting 是服务的一个可设置项。
type Setting struct {
	Key     string `msgpack:"key"`
	Default string `msgpack:"default,omitempty"`
}

// RegisterPayload 是 register 请求的 payload：服务名片。
type RegisterPayload struct {
	Name        string    `msgpack:"name"`
	Addr        string    `msgpack:"addr"`
	Description string    `msgpack:"description,omitempty"`
	Provides    []Provide `msgpack:"provides,omitempty"`
	Settings    []Setting `msgpack:"settings,omitempty"`
}

// ServiceCard 是 roster 中一个服务的公开部分。
type ServiceCard struct {
	Name        string    `msgpack:"name"`
	Addr        string    `msgpack:"addr"`
	Description string    `msgpack:"description,omitempty"`
	Provides    []Provide `msgpack:"provides,omitempty"`
}

// Card 返回名片去掉私有部分（settings）后的公开视图。
func (r RegisterPayload) Card() ServiceCard {
	return ServiceCard{
		Name:        r.Name,
		Addr:        r.Addr,
		Description: r.Description,
		Provides:    r.Provides,
	}
}

// ResponsePayload 是通用响应的 payload。
type ResponsePayload struct {
	OK    bool               `msgpack:"ok"`
	Data  msgpack.RawMessage `msgpack:"data,omitempty"`
	Error string             `msgpack:"error,omitempty"`
}

// RosterPayload 是全局服务清单（register 响应与 roster 事件共用）。
type RosterPayload struct {
	Services []ServiceCard `msgpack:"services"`
	Revision int64         `msgpack:"revision"`
}

// JumpPayload 是一次跳转访问：目标服务上的动作 + 输入。
type JumpPayload struct {
	Action string             `msgpack:"action"`
	Input  msgpack.RawMessage `msgpack:"input,omitempty"`
}

// HeartbeatPayload 是报活 payload。
type HeartbeatPayload struct {
	Status string `msgpack:"status,omitempty"`
}
