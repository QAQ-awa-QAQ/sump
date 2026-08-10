/* ============================================================
   SUMP Studio — Markdown & Message Renderer
   ============================================================ */

import { marked } from "marked";
import { markedHighlight } from "marked-highlight";
import hljs from "highlight.js";

// ---- Markdown Setup ----

marked.use(
  markedHighlight({
    langPrefix: "hljs language-",
    highlight(code: string, lang: string) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return hljs.highlightAuto(code).value;
    },
  }),
);

marked.setOptions({ breaks: true, gfm: true });

// ---- Helpers ----

export function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

export function renderMarkdown(text: string): string {
  return marked.parse(text) as string;
}

// ---- Message Builders ----

export function buildUserBubble(text: string): HTMLElement {
  const div = document.createElement("div");
  div.className = "message-row user";
  div.innerHTML = `<div class="message-bubble user-bubble">${escapeHtml(text)}</div>`;
  return div;
}

export function buildAssistantContainer(): { container: HTMLElement; content: HTMLElement } {
  const row = document.createElement("div");
  row.className = "message-row assistant";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble assistant-bubble";

  const content = document.createElement("div");
  content.className = "message-content";
  bubble.appendChild(content);

  row.appendChild(bubble);
  return { container: row, content };
}

export function buildToolCall(name: string, args: Record<string, string>): HTMLElement {
  const div = document.createElement("div");
  div.className = "tool-call-info";
  const argsStr = JSON.stringify(args, null, 2);
  div.innerHTML = `<span class="tool-icon">⚙</span> 调用工具 <code>${escapeHtml(name)}</code><pre>${escapeHtml(argsStr)}</pre>`;
  return div;
}

export function buildToolResult(text: string): HTMLElement {
  const div = document.createElement("div");
  div.className = "tool-result-info";
  div.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
  return div;
}

export function buildThinkingIndicator(): HTMLElement {
  const div = document.createElement("div");
  div.className = "thinking-indicator";
  div.innerHTML = '<span class="thinking-label">🧠 深度思考</span><span class="thinking-content"></span>';
  return div;
}

export function buildSecurityInfo(
  command: string, summary: string, danger: string,
  concerns: string[], verdict: string, callId: string,
): HTMLElement {
  const cls = verdict === "risky" ? "security-info risky" : "security-info safe";
  const div = document.createElement("div");
  div.className = cls;
  div.setAttribute("data-call-id", callId);
  div.innerHTML = `
    <div class="sec-header">
      <span class="sec-verdict">${verdict === "risky" ? "🔴 危险" : "🟢 安全"}</span>
      <span class="sec-summary">${escapeHtml(summary)}</span>
    </div>
    <div class="sec-detail">
      <div>命令: <code>${escapeHtml(command)}</code></div>
      <div>危险等级: ${escapeHtml(danger)}</div>
      ${concerns.length ? `<div>关切: ${escapeHtml(concerns.join(", "))}</div>` : ""}
    </div>
    <div class="sec-actions">
      <button class="btn-deny" data-deny="${callId}">拒绝</button>
      <button class="btn-approve" data-approve="${callId}">同意</button>
    </div>`;
  return div;
}
