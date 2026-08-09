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
  type StreamChunk,
  createSession,
  listSessions,
  deleteSession,
  streamChat,
} from "./api";

// ---- State ----

let currentSession: Session | null = null;
let sessions: Session[] = [];
let isStreaming = false;
let abortController: AbortController | null = null;

// ---- DOM Elements ----

const $sessionList = document.getElementById("session-list")!;
const $chatMessages = document.getElementById("chat-messages")!;
const $inputMessage = document.getElementById("input-message") as HTMLTextAreaElement;
const $btnSend = document.getElementById("btn-send") as HTMLButtonElement;
const $btnNewSession = document.getElementById("btn-new-session")!;
const $toggleThinking = document.getElementById("toggle-thinking")!;
const $currentSessionName = document.getElementById("current-session-name")!;
const $btnSettings = document.getElementById("btn-settings")!;
const $settingsDropdown = document.getElementById("settings-dropdown")!;
const $effortSection = document.getElementById("effort-section")!;
const $csModel = document.getElementById("custom-select-model")!;
const $csEffort = document.getElementById("custom-select-effort")!;

// ---- Settings State ----

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
  initCustomSelect($csModel);
  initCustomSelect($csEffort);
  bindEvents();
}

// ---- Session Management ----

async function refreshSessions() {
  sessions = await listSessions();
  renderSessionList();
}

function renderSessionList() {
  $sessionList.innerHTML = sessions
    .map(
      (s) => `
    <div class="session-item${currentSession?.id === s.id ? " active" : ""}" data-id="${s.id}">
      <span class="name">${escapeHtml(s.name)}</span>
      <button class="delete-btn" data-delete="${s.id}">×</button>
    </div>`,
    )
    .join("");
}

function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function selectSession(id: string) {
  const session = sessions.find((s) => s.id === id);
  if (!session) return;
  currentSession = session;
  applySettings(session.settings);
  $currentSessionName.textContent = session.name;
  renderSessionList();
  clearChat();
  $inputMessage.focus();
}

async function handleNewSession() {
  const session = await createSession();
  sessions.unshift(session);
  currentSession = session;
  $currentSessionName.textContent = session.name;
  applySettings(session.settings);
  renderSessionList();
  clearChat();
  $inputMessage.focus();
}

async function handleDeleteSession(e: MouseEvent) {
  const btn = (e.target as HTMLElement).closest("[data-delete]");
  if (!btn) return;
  e.stopPropagation();
  const id = btn.getAttribute("data-delete")!;
  await deleteSession(id);
  if (currentSession?.id === id) {
    currentSession = null;
    clearChat();
  }
  await refreshSessions();
}

function clearChat() {
  $chatMessages.innerHTML = "";
  $currentSessionName.textContent = currentSession?.name || "SUMP Studio";
  if (!currentSession) {
    $chatMessages.innerHTML = `
      <div class="welcome">
        <div class="welcome-icon">
          <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
          </svg>
        </div>
        <h2>欢迎使用 SUMP Studio</h2>
        <p>智能记忆平台 · 流式对话 · 深度思考</p>
        <div class="welcome-hints"><span>试试问我：帮我分析一个复杂问题</span></div>
      </div>`;
  }
}

// ---- Chat ----

async function handleSend() {
  if (isStreaming) return;

  // 无会话时自动新建
  if (!currentSession) {
    const session = await createSession();
    sessions.unshift(session);
    currentSession = session;
    $currentSessionName.textContent = session.name;
    renderSessionList();
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
    currentSession.id,
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
            thinkingContentEl = document.createElement("div");
            thinkingContentEl.className = "thinking-content";
            thinkingEl.appendChild(thinkingContentEl);
            thinkingEl.addEventListener("click", (e) => {
              const bar = e.currentTarget as HTMLElement;
              bar.classList.toggle("expanded");
              const inner = bar.querySelector(".thinking-content") as HTMLElement;
              if (inner) inner.classList.toggle("open");
            });
            assistantEl.querySelector(".msg-content")!.prepend(thinkingEl);
          }
          thinkingContentEl!.textContent = thinkingText;
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

        case "error":
          addMessage("error", chunk.text);
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

// ---- Events ----

function bindEvents() {
  $btnNewSession.addEventListener("click", handleNewSession);

  $sessionList.addEventListener("click", (e) => {
    const item = (e.target as HTMLElement).closest(".session-item");
    if (item) {
      const id = item.getAttribute("data-id")!;
      selectSession(id);
    }
  });

  $sessionList.addEventListener("click", handleDeleteSession);

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
