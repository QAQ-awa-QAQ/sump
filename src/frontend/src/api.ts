/* ============================================================
   API Client — 与 SUMP 后端通信
   ============================================================ */

const BASE = "/api";

export interface Session {
  id: string;
  name: string;
  created_at: string;
  message_count: number;
  settings: SessionSettings;
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

export async function getSession(id: string): Promise<Session> {
  const res = await fetch(`${BASE}/sessions/${id}`);
  return res.json();
}

export async function deleteSession(id: string): Promise<void> {
  await fetch(`${BASE}/sessions/${id}`, { method: "DELETE" });
}

export async function updateSessionSettings(id: string, settings: Partial<SessionSettings>): Promise<Session> {
  const res = await fetch(`${BASE}/sessions/${id}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  return res.json();
}

// ---- Models ----

export async function listModels(): Promise<Model[]> {
  const res = await fetch(`${BASE}/models`);
  return res.json();
}

// ---- Streaming Chat ----

export type StreamChunk =
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
