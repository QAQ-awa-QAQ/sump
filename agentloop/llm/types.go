package llm

// OpenAI 兼容的对话与工具调用类型（DeepSeek API 同构）。

// Message 是一条对话消息。
type Message struct {
	Role       string     `json:"role"`                   // system / user / assistant / tool
	Content    string     `json:"content,omitempty"`      // 文本内容
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`   // assistant 发起的工具调用
	ToolCallID string     `json:"tool_call_id,omitempty"` // tool 结果对应哪次调用
}

// ToolCall 是 assistant 发起的一次工具调用。
type ToolCall struct {
	ID       string       `json:"id"`
	Type     string       `json:"type"` // "function"
	Function FunctionCall `json:"function"`
}

// FunctionCall 是工具调用的函数名与参数（arguments 为 JSON 字符串）。
type FunctionCall struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

// Tool 是可提供给模型的工具定义。
type Tool struct {
	Type     string       `json:"type"` // "function"
	Function ToolFunction `json:"function"`
}

// ToolFunction 描述一个工具。
type ToolFunction struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"` // JSON Schema
}

// ChatRequest 是一次补全请求。
type ChatRequest struct {
	Model    string    `json:"model"`
	Messages []Message `json:"messages"`
	Tools    []Tool    `json:"tools,omitempty"`
}

// ChatResponse 是补全响应（OpenAI 兼容）。
type ChatResponse struct {
	Choices []Choice  `json:"choices"`
	Error   *APIError `json:"error,omitempty"`
}

// Choice 是响应中的一个候选。
type Choice struct {
	Message Message `json:"message"`
}

// APIError 是 API 返回的错误。
type APIError struct {
	Message string `json:"message"`
}
