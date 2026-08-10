/* ============================================================
   SUMP Studio — Main Entry
   ============================================================ */

import { marked } from "marked";
import { markedHighlight } from "marked-highlight";
import hljs from "highlight.js";
import "highlight.js/styles/github.css";

// 配置 marked + highlight.js
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

marked.setOptions({
  breaks: true,
  gfm: true,
});
import {
  type Session,
  type SessionSettings,
  type SessionDetail,
  type StreamChunk,
  createSession,
  listSessions,
  getSessionDetail,
  activateSession,
  deleteSession,
  renameSession,
  streamChat,
  approveTool,
} from "./api";

// ---- State ----

let currentSessionId: string | null = localStorage.getItem("sump_session_id");
let chatSessionId: string | null = null;
let sessions: Session[] = [];
let isStreaming = false;
let abortController: AbortController | null = null;
/* 注意：abortController 仅供 handleSend 使用；sendContinue 使用局部变量互不干扰 */

// ---- DOM Elements ----

const $sessionList = document.getElementById("session-list")!;
const $chatMessages = document.getElementById("chat-messages")!;
const $inputMessage = document.getElementById("input-message") as HTMLTextAreaElement;
const $btnSend = document.getElementById("btn-send") as HTMLButtonElement;
const $btnNewSession = document.getElementById("btn-new-session")!;
const $toggleThinking = document.getElementById("toggle-thinking")!;
const $toggleTrackThinking = document.getElementById("toggle-track-thinking")!;
const $toggleAutoApprove = document.getElementById("toggle-auto-approve")!;
const $currentSessionName = document.getElementById("current-session-name")!;
const $btnSettings = document.getElementById("btn-settings")!;
const $settingsDropdown = document.getElementById("settings-dropdown")!;
const $effortSection = document.getElementById("effort-section")!;
const $csModel = document.getElementById("custom-select-model")!;
const $csEffort = document.getElementById("custom-select-effort")!;

// ---- Settings State ----

let autoTrackThinking = true;

function getSettings(): SessionSettings {
  return {
    model: $csModel.querySelector(".cs-trigger")!.getAttribute("data-value") || "deepseek-v4-flash",
    reasoning_effort: $csEffort.querySelector(".cs-trigger")!.getAttribute("data-value") || "high",
    thinking_enabled: $toggleThinking.classList.contains("active"),
  };
}

function applySettings(settings: SessionSettings) {
  setCustomSelectValue($csModel, settings.model);
  setCustomSelectValue($csEffort, settings.reasoning_effort);
  if (settings.thinking_enabled) {
    $toggleThinking.classList.add("active");
    $toggleThinking.setAttribute("aria-checked", "true");
    $effortSection.classList.add("open");
  } else {
    $toggleThinking.classList.remove("active");
    $toggleThinking.setAttribute("aria-checked", "false");
    $effortSection.classList.remove("open");
  }
}

// ---- Custom Select ----

function setCustomSelectValue(container: HTMLElement, value: string) {
  const trigger = container.querySelector(".cs-trigger")!;
  const label = trigger.querySelector(".cs-label")!;
  const options = container.querySelectorAll(".cs-option");

  trigger.setAttribute("data-value", value);
  options.forEach((opt) => {
    const el = opt as HTMLElement;
    if (el.getAttribute("data-value") === value) {
      el.classList.add("selected");
      label.textContent = el.textContent || "";
    } else {
      el.classList.remove("selected");
    }
  });
}

function initCustomSelect(container: HTMLElement) {
  const trigger = container.querySelector(".cs-trigger")! as HTMLElement;

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    closeAllCustomSelects(container);
    container.classList.toggle("open");
  });

  container.querySelectorAll(".cs-option").forEach((opt) => {
    opt.addEventListener("click", (e) => {
      e.stopPropagation();
      const value = (opt as HTMLElement).getAttribute("data-value")!;
      setCustomSelectValue(container, value);
      container.classList.remove("open");
    });
  });
}

function closeAllCustomSelects(except?: HTMLElement) {
  [$csModel, $csEffort].forEach((cs) => {
    if (cs !== except) cs.classList.remove("open");
  });
}

document.addEventListener("click", () => closeAllCustomSelects());

// ---- Init ----

async function init() {
  await refreshSessions();
  if (currentSessionId) {
    try { await loadSession(currentSessionId); } catch { currentSessionId = null; localStorage.removeItem("sump_session_id"); }
  }
  initCustomSelect($csModel);
  initCustomSelect($csEffort);
  bindEvents();
}

// ---- Session Management ----

async function refreshSessions() {
  try { sessions = await listSessions(); } catch { sessions = []; }
  renderSessionList();
}

function renderSessionList() {
  $sessionList.innerHTML = sessions
    .map((s) => `
    <div class="session-item${currentSessionId === s.id ? " active" : ""}" data-sid="${s.id}">
      <span class="name">${escapeHtml(s.name || s.id.slice(0, 8))}</span>
      <span class="count">${s.msg_count}</span>
      <button class="edit-btn" data-edit="${s.id}" title="重命名">
        <svg width="14" height="14" viewBox="0 0 256 256" fill="none" stroke="currentColor" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
          <path d="M96 216L48 216L48 168L192 24L232 64Z" />
          <line x1="168" y1="48" x2="208" y2="88" />
        </svg>
      </button>
      <button class="delete-btn" data-delete="${s.id}" title="删除">×</button>
    </div>`)
    .join("");
}

function startRename(sid: string, currentName: string) {
  const item = $sessionList.querySelector(`[data-sid="${sid}"]`);
  const nameEl = item?.querySelector(".name") as HTMLElement | null;
  if (!nameEl) return;

  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = currentName;
  input.setSelectionRange(0, input.value.length);

  const commit = async () => {
    const newName = input.value.trim();
    input.replaceWith(document.createTextNode(""));
    if (newName && newName !== currentName) {
      try {
        await renameSession(sid, newName);
        const session = sessions.find((s) => s.id === sid);
        if (session) session.name = newName;
        renderSessionList();
        if (sid === currentSessionId) {
          $currentSessionName.textContent = newName;
        }
      } catch { renderSessionList(); }
    } else {
      renderSessionList();
    }
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    if (e.key === "Escape") { input.value = currentName; input.blur(); }
  });
  input.addEventListener("blur", commit);

  nameEl.replaceWith(input);
  input.focus();
}

async function handleNewSession() {
  currentSessionId = null;
  chatSessionId = null;
  localStorage.removeItem("sump_session_id");
  clearChat();
  $currentSessionName.textContent = "SUMP Studio";
  $inputMessage.focus();
}

function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function loadSession(id: string) {
  try {
    await activateSession(id);
    const detail = await getSessionDetail(id);
    const s = await createSession();
    chatSessionId = s.id;
    $chatMessages.innerHTML = "";

    let currentAssistantEl: HTMLElement | null = null;
    detail.messages.forEach((msg: any) => {
      if (msg.role === "user") {
        currentAssistantEl = null;
        addMessage("user", msg.content);
      } else if (msg.role === "assistant") {
        const el = addMessage("assistant", "");
        const mc = el.querySelector(".msg-content")!;

        // 恢复思考内容
        if (msg.reasoning_content) {
          const thinkingBar = document.createElement("div");
          thinkingBar.className = "thinking-indicator-bar done";
          thinkingBar.innerHTML = '<span class="thinking-label">深度思考已完成</span>';
          const thinkingContent = document.createElement("div");
          thinkingContent.className = "thinking-content";
          thinkingContent.textContent = msg.reasoning_content;
          thinkingBar.appendChild(thinkingContent);
          thinkingBar.addEventListener("click", (e) => {
            const bar = e.currentTarget as HTMLElement;
            const inner = bar.querySelector(".thinking-content") as HTMLElement;
            if (inner) {
              const opening = !inner.classList.contains("open");
              inner.classList.toggle("open");
              if (opening) bar.classList.add("expanded");
              else bar.classList.remove("expanded");
              scrollToUserMsg(bar);
            }
          });
          mc.appendChild(thinkingBar);
        }

        if (msg.tool_calls?.length) {
          for (const tc of msg.tool_calls) {
            const t = document.createElement("div");
            t.className = "tool-call-msg";
            t.innerHTML = `<span class="tool-icon">&#9881;</span> 调用工具 <code>${escapeHtml((tc.function || tc).name)}</code>`;
            mc.appendChild(t);
          }
        }
        if (msg.content) {
          const c = document.createElement("div");
          c.className = "assistant-content";
          c.innerHTML = marked.parse(msg.content) as string;
          mc.appendChild(c);
        }
        currentAssistantEl = el;
      } else if (msg.role === "tool") {
        const content = msg.content || "";
        // 解析"⛔ 安全审查待确认"格式
        const pendingMatch = content.match(/⛔ 安全审查待确认 \| call_id: (\S+) \| 命令: (.+?) \| 意图: (.+?) \| 危险等级: (\S+)/);
        if (pendingMatch) {
          const info = document.createElement("div");
          info.className = "security-info";
          info.innerHTML =
            `<div class="si-row"><span class="si-label">命令：</span><code>${escapeHtml(pendingMatch[2])}</code></div>` +
            `<div class="si-row"><span class="si-label">危险等级：</span><span class="sd-danger sd-${pendingMatch[4]}">${pendingMatch[4]}</span></div>` +
            `<div class="si-row"><span class="si-label">作用：</span>${escapeHtml(pendingMatch[3])}</div>` +
            `<div class="si-row" style="margin-top:4px;color:var(--color-muted);font-style:italic">⏳ 等待审批</div>`;
          (currentAssistantEl?.querySelector(".msg-content") ?? $chatMessages).appendChild(info);
        } else {
          const t = document.createElement("div");
          t.className = "tool-result-msg";
          t.textContent = content;
          (currentAssistantEl?.querySelector(".msg-content") ?? $chatMessages).appendChild(t);
        }
      }
    });

    currentSessionId = id;
    localStorage.setItem("sump_session_id", id);
    // 从会话列表中取 name
    const found = sessions.find((s) => s.id === id);
    $currentSessionName.textContent = found?.name || id.slice(0, 8);
    renderSessionList();
    scrollToBottom();
  } catch { /* ignore */ }
}

function clearChat() {
  $chatMessages.innerHTML = "";
  if (!currentSessionId) {
    $chatMessages.innerHTML = `
      <div class="welcome">
        <div class="welcome-icon"><svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg></div>
        <h2>欢迎使用 SUMP Studio</h2>
        <p>智能记忆平台 · 流式对话 · 深度思考</p>
        <div class="welcome-hints"><span>试试问我：帮我分析一个复杂问题</span></div>
      </div>`;
  }
}

// ---- Chat ----

async function handleSend() {
  if (isStreaming) return;

  // 首次发言：创建会话
  if (!currentSessionId) {
    try {
      const mem = await createSession();
      currentSessionId = mem.id;
      localStorage.setItem("sump_session_id", currentSessionId);
      await refreshSessions();
    } catch { /* 后端未就绪 */ }
  }
  if (!chatSessionId) {
    const s = await createSession();
    chatSessionId = s.id;
  }

  const message = $inputMessage.value.trim();
  if (!message) return;

  // UI state
  isStreaming = true;
  $btnSend.disabled = true;
  $inputMessage.value = "";
  $inputMessage.style.height = "auto";

  // Remove welcome
  const welcomeEl = $chatMessages.querySelector(".welcome");
  if (welcomeEl) welcomeEl.remove();

  // Add user message
  addMessage("user", message);

  // Add assistant placeholder
  const assistantEl = addMessage("assistant", "");
  let contentEl: HTMLElement | null = null;
  let thinkingEl: HTMLElement | null = null;
  let thinkingContentEl: HTMLElement | null = null;
  let thinkingText = "";
  let rawContent = "";

  // Stream
  abortController = streamChat(
    chatSessionId!,
    message,
    getSettings(),
    (chunk: StreamChunk) => {
      switch (chunk.type) {
        case "reasoning":
          thinkingText += chunk.text;
          if (!thinkingEl) {
            thinkingEl = document.createElement("div");
            thinkingEl.className = "thinking-indicator-bar";
            thinkingEl.innerHTML = '<span class="thinking-label">深度思考中…</span>';
            // 追踪指示点
            const trackDot = document.createElement("span");
            trackDot.className = "track-dot";
            thinkingEl.appendChild(trackDot);
            thinkingContentEl = document.createElement("div");
            thinkingContentEl.className = "thinking-content";
            thinkingEl.appendChild(thinkingContentEl);

            // 点击展开/折叠 → 滚动到对应用户消息
            thinkingEl.addEventListener("click", (e) => {
              const bar = e.currentTarget as HTMLElement;
              const inner = bar.querySelector(".thinking-content") as HTMLElement;
              if (inner) {
                const opening = !inner.classList.contains("open");
                inner.classList.toggle("open");
                if (opening) bar.classList.add("expanded");
                else bar.classList.remove("expanded");
                scrollToUserMsg(bar);
              }
            });

            // 思考内容滚动追踪
            thinkingContentEl.addEventListener("scroll", () => {
              if (!autoTrackThinking || !thinkingContentEl) return;
              const el = thinkingContentEl;
              const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
              const trackDot = thinkingEl?.querySelector(".track-dot");
              if (atBottom) {
                trackDot?.classList.remove("paused");
              } else {
                trackDot?.classList.add("paused");
              }
            });

            assistantEl.querySelector(".msg-content")!.prepend(thinkingEl);

            // 自动展开
            if (autoTrackThinking) {
              thinkingContentEl.classList.add("open");
              thinkingEl.classList.add("expanded");
              scrollToBottom();
            }
          }
          thinkingContentEl!.textContent = thinkingText;
          // 自动滚动思考内容 + 聊天窗口
          if (autoTrackThinking && thinkingContentEl) {
            const el = thinkingContentEl;
            const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
            if (atBottom || !el.classList.contains("open")) {
              el.scrollTop = el.scrollHeight;
            }
            scrollToBottom();
          }
          break;

        case "tool_call":
          {
            const toolMsg = document.createElement("div");
            toolMsg.className = "tool-call-msg";
            const argsStr = chunk.args ? ` <span class="tool-args">${escapeHtml(JSON.stringify(chunk.args))}</span>` : "";
            toolMsg.innerHTML = `<span class="tool-icon">&#9881;</span> 调用工具 <code>${escapeHtml(chunk.name)}</code>${argsStr}`;
            assistantEl.querySelector(".msg-content")!.appendChild(toolMsg);
            scrollToBottom();
          }
          break;

        case "tool_result":
          {
            const resultMsg = document.createElement("div");
            resultMsg.className = "tool-result-msg";
            resultMsg.textContent = chunk.content;
            assistantEl.querySelector(".msg-content")!.appendChild(resultMsg);
            scrollToBottom();
          }
          break;

        case "security_check":
          if (!chunk.call_id) {
            // 纯信息展示（规则秒出 / LLM Flash），无需审批动作
            if (chunk.verdict === "unknown") {
              showSecurityPending(chunk);
            }
          } else if (chunk.verdict === "safe") {
            // safe: 默认弹确认框，开了自动同意才跳过
            if ($toggleAutoApprove.classList.contains("active")) {
              autoApprove(chunk.call_id);
            } else {
              showSecurityDialog(chunk);
            }
          } else if (chunk.verdict === "risky") {
            if (chunk.danger === "low" && $toggleAutoApprove.classList.contains("active")) {
              autoApprove(chunk.call_id);
            } else {
              showSecurityDialog(chunk);
            }
          } else {
            // 未知裁决，显示等待
            showSecurityPending(chunk);
          }
          break;

        case "security_check_detail":
          updateSecurityDetail(chunk);
          break;

        case "content":
          if (thinkingEl) {
            const label = thinkingEl.querySelector(".thinking-label")!;
            label.textContent = "深度思考已完成";
            thinkingContentEl!.textContent = thinkingText;
            thinkingEl.classList.add("done");
            thinkingEl = null;
          }
          if (!contentEl) {
            contentEl = document.createElement("div");
            contentEl.className = "assistant-content";
            assistantEl.querySelector(".msg-content")!.appendChild(contentEl);
          }
          rawContent += chunk.text;
          contentEl.innerHTML = marked.parse(rawContent) as string;
          scrollToBottom();
          break;

        case "session_name":
          // 更新侧边栏会话名 + 顶部标题
          {
            const idx = sessions.findIndex((s) => s.id === chunk.session_id);
            if (idx !== -1) {
              sessions[idx].name = chunk.name;
            }
            renderSessionList();
            if (chunk.session_id === currentSessionId) {
              $currentSessionName.textContent = chunk.name;
            }
          }
          break;

        case "error":
          addMessage("error", chunk.text);
          break;

        case "continue":
          {
            // 替换对应"待确认"消息（SSE 流中收到时）
            const msgs = $chatMessages.querySelectorAll(".message.assistant");
            const lastAssistant = msgs[msgs.length - 1];
            if (lastAssistant) {
              const mc = lastAssistant.querySelector(".msg-content") as HTMLElement | null;
              if (mc) mc.innerHTML = `<div class="assistant-content">${escapeHtml(chunk.text)}</div>`;
            }
            scrollToBottom();
          }
          break;

        case "done":
          if (thinkingEl) {
            const label = thinkingEl.querySelector(".thinking-label")!;
            label.textContent = "深度思考已完成";
            thinkingContentEl!.textContent = thinkingText;
            thinkingEl.classList.add("done");
          }
          break;
      }
    },
  );

  isStreaming = false;
  $btnSend.disabled = false;
  $inputMessage.focus();
  // 刷新侧边栏（更新消息数）
  refreshSessions();
}

function addMessage(role: "user" | "assistant" | "error", text: string): HTMLElement {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  const content = document.createElement("div");
  content.className = "msg-content";
  if (text && role !== "assistant") {
    content.textContent = text;
  }
  div.appendChild(content);
  $chatMessages.appendChild(div);
  scrollToBottom();
  return div;
}

function scrollToBottom() {
  $chatMessages.scrollTop = $chatMessages.scrollHeight;
}

function scrollToUserMsg(thinkingBar: HTMLElement) {
  const assistantMsg = thinkingBar.closest(".message.assistant");
  if (!assistantMsg) return;
  const userMsg = assistantMsg.previousElementSibling as HTMLElement | null;
  if (!userMsg || !userMsg.classList.contains("user")) return;
  const chatRect = $chatMessages.getBoundingClientRect();
  const userRect = userMsg.getBoundingClientRect();
  $chatMessages.scrollTo({
    top: $chatMessages.scrollTop + userRect.top - chatRect.top - 10,
    behavior: "smooth",
  });
}

// ---- Security ----

const _securityDialogs: Map<string, HTMLElement> = new Map();
const _pendingMessages: Map<string, HTMLElement> = new Map();

function showSecurityToast(command: string) {
  const toast = document.createElement("div");
  toast.className = "security-toast";
  toast.innerHTML = `<span>&#128737;</span> 安全执行 <code>${escapeHtml(command)}</code>`;
  document.body.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));
  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

function showSecurityPending(chunk: SecurityCheckChunk) {
  // 显示"分析中"占位，不弹窗
  const msgs = $chatMessages.querySelectorAll(".message.assistant");
  const lastAssistant = msgs[msgs.length - 1];
  if (lastAssistant) {
    const mc = lastAssistant.querySelector(".msg-content") as HTMLElement | null;
    if (mc) {
      const el = document.createElement("div");
      el.className = "security-pending";
      el.innerHTML = `<span class="tool-icon">&#128737;</span> 安全审查中… <code>${escapeHtml(chunk.command)}</code>`;
      mc.appendChild(el);
      _pendingMessages.set(chunk.call_id, el);
    }
  }
}

function updateSecurityDetail(chunk: Extract<StreamChunk, { type: "security_check_detail" }>) {
  // 替换 pending 占位为实际分析
  const pending = _pendingMessages.get(chunk.call_id);
  if (pending) {
    pending.className = "security-info";
    pending.innerHTML =
      `<div class="si-row"><span class="si-label">命令：</span><code>${escapeHtml(chunk.command)}</code></div>` +
      `<div class="si-row"><span class="si-label">危险等级：</span><span class="sd-danger sd-${chunk.danger}">${chunk.danger}</span></div>` +
      `<div class="si-row"><span class="si-label">作用：</span>${escapeHtml(chunk.summary)}</div>`;
    _pendingMessages.delete(chunk.call_id);
  }
  // 也更新已有的弹窗
  updateSecurityDialog(chunk);
}

function buildSecurityDialog(chunk: SecurityCheckChunk): string {
  const isSafe = chunk.verdict === "safe";
  const headerIcon = isSafe ? "&#9989;" : "&#9888;";
  const headerText = isSafe ? "命令执行确认" : "危险命令确认";
  const headerClass = isSafe ? "sd-safe" : "sd-risky";
  return `
    <div class="security-dialog">
      <div class="sd-header ${headerClass}">${headerIcon} ${headerText}</div>
      <div class="sd-body">
        <div class="sd-row"><label>命令</label><code>${escapeHtml(chunk.command)}</code></div>
        <div class="sd-row"><label>危险等级</label><span class="sd-danger sd-${chunk.danger}">${chunk.danger}</span></div>
        <div class="sd-row sd-summary-row"><label>${chunk.analysis_source === "rules" ? "初步分析" : "详细分析"}</label><span class="sd-summary-text">${escapeHtml(chunk.summary)}</span></div>
        ${chunk.concerns.length ? `<div class="sd-row sd-concerns-row"><label>关切点</label>${chunk.concerns.map(c => `<span class="sd-concern">${escapeHtml(c)}</span>`).join(" ")}</div>` : ""}
      </div>
      <div class="sd-actions">
        <button class="sd-btn sd-reject">&#10060; 拒绝</button>
        <button class="sd-btn sd-approve">&#9989; 同意执行</button>
      </div>
    </div>`;
}

type SecurityCheckChunk = Extract<StreamChunk, { type: "security_check" }>;

function showSecurityDialog(chunk: SecurityCheckChunk) {
  const overlay = document.createElement("div");
  overlay.className = "security-overlay";
  overlay.innerHTML = buildSecurityDialog(chunk);
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("show"));

  _securityDialogs.set(chunk.call_id, overlay);
  // 记住包含"待确认"的 assistant 消息元素
  const msgs = $chatMessages.querySelectorAll(".message.assistant");
  _pendingMessages.set(chunk.call_id, msgs[msgs.length - 1] as HTMLElement);
  bindDialogActions(overlay, chunk.call_id);
}

function updateSecurityDialog(chunk: Extract<StreamChunk, { type: "security_check_detail" }>) {
  const overlay = _securityDialogs.get(chunk.call_id);
  if (!overlay) return;
  const dialog = overlay.querySelector(".security-dialog")!;
  dialog.innerHTML = buildSecurityDialog(chunk as any);
  bindDialogActions(overlay, chunk.call_id);
}

async function autoApprove(callId: string) {
  try {
    const res = await approveTool(callId, true) as any;
    const msgs = $chatMessages.querySelectorAll(".message.assistant");
    const lastAssistant = msgs[msgs.length - 1];
    if (lastAssistant) {
      // 先移除所有 "⛔ 安全审查待确认" 占位消息
      lastAssistant.querySelectorAll(".tool-result-msg").forEach(el => {
        if (el.textContent?.includes("⛔ 安全审查待确认")) el.remove();
      });
      // 追加工具实际执行结果
      if (res.result && !res.result.includes("⛔ 安全审查待确认")) {
        const resultMsg = document.createElement("div");
        resultMsg.className = "tool-result-msg";
        resultMsg.textContent = res.result;
        lastAssistant.querySelector(".msg-content")!.appendChild(resultMsg);
      }
    }
    scrollToBottom();
    if (res.continue) sendContinue();
  } catch { /* ignore */ }
}

async function sendContinue() {
  if (!chatSessionId) return;
  isStreaming = true;
  $btnSend.disabled = true;
  const assistantEl = addMessage("assistant", "");
  let contentEl: HTMLElement | null = null;
  let rawContent = "";
  const _ctrl = streamChat(chatSessionId, "__continue__", getSettings(), (chunk: StreamChunk) => {
    if (chunk.type === "content") {
      if (!contentEl) {
        contentEl = document.createElement("div");
        contentEl.className = "assistant-content";
        assistantEl.querySelector(".msg-content")!.appendChild(contentEl);
      }
      rawContent += chunk.text;
      contentEl.innerHTML = marked.parse(rawContent) as string;
      scrollToBottom();
    } else if (chunk.type === "tool_call") {
      const toolMsg = document.createElement("div");
      toolMsg.className = "tool-call-msg";
      toolMsg.innerHTML = `<span class="tool-icon">&#9881;</span> 调用工具 <code>${escapeHtml(chunk.name)}</code>`;
      assistantEl.querySelector(".msg-content")!.appendChild(toolMsg);
      scrollToBottom();
    } else if (chunk.type === "tool_result") {
      const resultMsg = document.createElement("div");
      resultMsg.className = "tool-result-msg";
      resultMsg.textContent = chunk.content;
      assistantEl.querySelector(".msg-content")!.appendChild(resultMsg);
      scrollToBottom();
    } else if (chunk.type === "security_check") {
      if (chunk.call_id && chunk.verdict === "safe") {
        if ($toggleAutoApprove.classList.contains("active")) {
          autoApprove(chunk.call_id);
        } else {
          showSecurityDialog(chunk);
        }
      } else if (chunk.call_id && chunk.verdict === "risky") {
        if (chunk.danger === "low" && $toggleAutoApprove.classList.contains("active")) {
          autoApprove(chunk.call_id);
        } else {
          showSecurityDialog(chunk);
        }
      }
    } else if (chunk.type === "security_check_detail") {
      updateSecurityDetail(chunk);
    } else if (chunk.type === "error") {
      addMessage("error", chunk.text);
    } else if (chunk.type === "done") {
      isStreaming = false;
      $btnSend.disabled = false;
      refreshSessions();
    }
  });
}

function bindDialogActions(overlay: HTMLElement, callId: string) {
  const dialog = overlay.querySelector(".security-dialog")!;
  const close = async (approved: boolean) => {
    _securityDialogs.delete(callId);
    overlay.classList.remove("show");
    setTimeout(() => overlay.remove(), 200);
    try {
      const res = await approveTool(callId, approved) as any;
      const msgEl = _pendingMessages.get(callId);
      if (msgEl) {
        const mc = msgEl.querySelector(".msg-content") as HTMLElement | null;
        if (mc) mc.innerHTML = `<div class="assistant-content">${escapeHtml(res.result || "")}</div>`;
        _pendingMessages.delete(callId);
      }
      scrollToBottom();
      if (res.continue) sendContinue();
    } catch {
      addMessage("error", "审批请求失败");
    }
  };
  dialog.querySelector(".sd-approve")!.addEventListener("click", () => close(true));
  dialog.querySelector(".sd-reject")!.addEventListener("click", () => close(false));
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(false); });
}

// ---- Events ----

function bindEvents() {
  $btnNewSession.addEventListener("click", handleNewSession);

  $sessionList.addEventListener("click", (e) => {
    const item = (e.target as HTMLElement).closest(".session-item");
    if (!item) return;

    // 删除按钮
    const delBtn = (e.target as HTMLElement).closest("[data-delete]");
    if (delBtn) {
      e.stopPropagation();
      const id = delBtn.getAttribute("data-delete")!;
      deleteSession(id);
      if (currentSessionId === id) {
        currentSessionId = null;
        localStorage.removeItem("sump_session_id");
        clearChat();
      }
      refreshSessions();
      return;
    }

    // 编辑（重命名）按钮
    const editBtn = (e.target as HTMLElement).closest("[data-edit]");
    if (editBtn) {
      e.stopPropagation();
      const sid = editBtn.getAttribute("data-edit")!;
      const session = sessions.find((s) => s.id === sid);
      if (!session) return;
      startRename(sid, session.name || sid.slice(0, 8));
      return;
    }

    const id = item.getAttribute("data-sid")!;
    loadSession(id);
  });

  $btnSend.addEventListener("click", handleSend);

  // Settings dropdown
  $btnSettings.addEventListener("click", (e) => {
    e.stopPropagation();
    $settingsDropdown.classList.toggle("hidden");
  });

  document.addEventListener("click", (e) => {
    if (!$settingsDropdown.classList.contains("hidden") &&
        !$settingsDropdown.contains(e.target as Node) &&
        e.target !== $btnSettings) {
      $settingsDropdown.classList.add("hidden");
    }
  });

  $toggleThinking.addEventListener("click", (e) => {
    e.stopPropagation();
    $toggleThinking.classList.toggle("active");
    const isActive = $toggleThinking.classList.contains("active");
    $toggleThinking.setAttribute("aria-checked", String(isActive));
    if (isActive) {
      $effortSection.classList.add("open");
    } else {
      $effortSection.classList.remove("open");
    }
  });

  $toggleTrackThinking.addEventListener("click", (e) => {
    e.stopPropagation();
    $toggleTrackThinking.classList.toggle("active");
    autoTrackThinking = $toggleTrackThinking.classList.contains("active");
    $toggleTrackThinking.setAttribute("aria-checked", String(autoTrackThinking));
    // 立即应用到所有已有的思考内容
    if (autoTrackThinking) {
      document.querySelectorAll(".thinking-content").forEach((el) => {
        el.classList.add("open");
        (el.parentElement as HTMLElement)?.classList.add("expanded");
        el.scrollTop = el.scrollHeight;
      });
    }
  });

  $toggleAutoApprove.addEventListener("click", (e) => {
    e.stopPropagation();
    $toggleAutoApprove.classList.toggle("active");
    const isActive = $toggleAutoApprove.classList.contains("active");
    $toggleAutoApprove.setAttribute("aria-checked", String(isActive));
  });

  $inputMessage.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  // Auto-resize textarea
  $inputMessage.addEventListener("input", () => {
    $inputMessage.style.height = "auto";
    $inputMessage.style.height = Math.min($inputMessage.scrollHeight, 200) + "px";
  });
}

// ---- Bootstrap ----

init();
