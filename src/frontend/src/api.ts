/* ============================================================
   API Client — 与 SUMP 后端通信
   ============================================================ */

const BASE = "/api";

export interface Session {
  id: string;
  msg_count: number;
  created_at: string;
}

export interface SessionDetail {
  id: string;
  messages: { role: string; content: string; tool_calls?: any[]; tool_call_id?: string }[];
}

export interface SessionSettings {
  model: string;
  reasoning_effort: string;
  thinking_enabled: boolean;
}

export interface Model {
  id: string;
  name: string;
  description: string;
}

export interface SSEClient {
  close(): void;
}

// ---- Sessions ----

export async function createSession(name = ""): Promise<Session> {
  const res = await fetch(`${BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return res.json();
}

export async function listSessions(): Promise<Session[]> {
  const res = await fetch(`${BASE}/sessions`);
  return res.json();
}

export async function getSessionDetail(id: string): Promise<SessionDetail> {
  const res = await fetch(`${BASE}/sessions/${id}`);
  return res.json();
}

export async function activateSession(id: string): Promise<void> {
  await fetch(`${BASE}/sessions/${id}/activate`, { method: "POST" });
}

export async function deleteSession(id: string): Promise<void> {
  await fetch(`${BASE}/sessions/${id}`, { method: "DELETE" });
}

// ---- Models ----

export async function listModels(): Promise<Model[]> {
  const res = await fetch(`${BASE}/models`);
  return res.json();
}

// ---- Streaming Chat ----

export type StreamChunk =
  | { type: "tool_call"; name: string; args: Record<string, string> }
  | { type: "tool_result"; content: string }
  | { type: "security_check"; verdict: string; call_id: string; command: string; summary: string; danger: string; concerns: string[]; analysis_source: string }
  | { type: "security_check_detail"; verdict: string; call_id: string; command: string; summary: string; danger: string; concerns: string[]; analysis_source: string }
  | { type: "continue"; text: string }
  | { type: "reasoning"; text: string }
  | { type: "content"; text: string }
  | { type: "error"; text: string }
  | { type: "done" };

export function streamChat(
  sessionId: string,
  message: string,
  settings: SessionSettings,
  onChunk: (chunk: StreamChunk) => void,
): AbortController {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/chat/${sessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, ...settings }),
        signal: controller.signal,
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") {
            onChunk({ type: "done" });
            return;
          }
          try {
            const parsed = JSON.parse(data) as StreamChunk;
            onChunk(parsed);
          } catch {
            // ignore malformed JSON
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        onChunk({ type: "error", text: (err as Error).message });
      }
    }
  })();

  return controller;
}

// ---- Tool Approval ----

export async function approveTool(callId: string, approved: boolean): Promise<{ result: string; continue?: boolean }> {
  const res = await fetch(`${BASE}/tools/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId, approved }),
  });
  return res.json();
}
