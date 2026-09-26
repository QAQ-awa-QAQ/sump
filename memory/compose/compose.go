// Package compose 负责“记忆块”的组装：从会话历史与任务上下文构造注入记忆后的消息链。
// 记忆的形态（内容、位置、替换策略）由记忆服务全权决定——调用方只把上下文托管过来。
package compose

import (
	"strings"

	"github.com/QAQ-awa-QAQ/sump/protocol"
)

// MemoryPrefix 是记忆消息的内容前缀（用于识别并替换自己的旧注入）。
const MemoryPrefix = "【记忆】"

// ConversationTail 提取任务上下文尾部的对话消息（user/assistant 文本），
// 遇到第一条 system（system prompt 或旧记忆块）即停——那是任务链的边界。
func ConversationTail(messages []protocol.Message) []protocol.Message {
	var tail []protocol.Message
	for i := len(messages) - 1; i >= 0; i-- {
		m := messages[i]
		if m.Role == "system" {
			break
		}
		if isDialogText(m) {
			tail = append(tail, m)
		}
	}
	// 反向收集 → 翻正
	for i, j := 0, len(tail)-1; i < j; i, j = i+1, j-1 {
		tail[i], tail[j] = tail[j], tail[i]
	}
	return tail
}

func isDialogText(m protocol.Message) bool {
	return (m.Role == "user" || m.Role == "assistant") &&
		strings.TrimSpace(m.Content) != "" && len(m.ToolCalls) == 0
}

// TrimOverlap 从 history 尾部裁去与 tail 尾部逐条相同（role+content）的部分——
// 任务链里已有的对话消息不再重复注入。
func TrimOverlap(history, tail []protocol.Message) []protocol.Message {
	i, j := len(history)-1, len(tail)-1
	for i >= 0 && j >= 0 {
		if history[i].Role != tail[j].Role || history[i].Content != tail[j].Content {
			break
		}
		i--
		j--
	}
	return history[:i+1]
}

// BuildText 把历史消息拼成“用户: … / 助手: …”的记忆文本。
func BuildText(history []protocol.Message) string {
	var b strings.Builder
	for _, m := range history {
		switch m.Role {
		case "user":
			b.WriteString("用户: ")
		case "assistant":
			b.WriteString("助手: ")
		default:
			continue
		}
		b.WriteString(strings.TrimSpace(m.Content))
		b.WriteString("\n")
	}
	return strings.TrimSpace(b.String())
}

// Inject 将记忆文本注入消息链：替换已有记忆块（保持原位置），否则插到第一条 system 之后；
// memoryText 为空时移除旧块（本链视为无记忆）。
func Inject(messages []protocol.Message, memoryText string) []protocol.Message {
	out := make([]protocol.Message, 0, len(messages)+1)
	placed := false
	for _, m := range messages {
		if m.Role == "system" && strings.HasPrefix(m.Content, MemoryPrefix) {
			if memoryText != "" && !placed {
				out = append(out, protocol.Message{Role: "system", Content: MemoryPrefix + "\n" + memoryText})
				placed = true
			}
			continue
		}
		out = append(out, m)
		if memoryText != "" && !placed && m.Role == "system" {
			out = append(out, protocol.Message{Role: "system", Content: MemoryPrefix + "\n" + memoryText})
			placed = true
		}
	}
	if memoryText != "" && !placed {
		out = append([]protocol.Message{{Role: "system", Content: MemoryPrefix + "\n" + memoryText}}, out...)
	}
	return out
}
