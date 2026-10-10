import type {
  CreateSessionRequest,
  HistoryResponse,
  PlayerProfileDTO,
  SessionDetailDTO,
  SessionSummaryDTO,
  TacticianInfoDTO,
  WsEvent,
} from "../types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* keep statusText */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),

  listTacticians: () => request<TacticianInfoDTO[]>("/tacticians"),

  createSession: (payload: CreateSessionRequest) =>
    request<SessionDetailDTO>("/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listSessions: () => request<SessionSummaryDTO[]>("/sessions"),

  getSession: (id: string) => request<SessionDetailDTO>(`/sessions/${id}`),

  startSession: (id: string) =>
    request<{ status: string }>(`/sessions/${id}/start`, { method: "POST" }),

  stopSession: (id: string) =>
    request<{ status: string }>(`/sessions/${id}/stop`, { method: "POST" }),

  getHistory: (id: string) => request<HistoryResponse>(`/history/${id}`),

  getProfiles: (id: string) =>
    request<{ profiles: PlayerProfileDTO[] }>(`/profiles/${id}`),

  exportUrl: (id: string) => `${BASE}/history/${id}/export`,
};

export interface WsHandle {
  close: () => void;
}

/**
 * Open the session WebSocket with automatic reconnect (exponential
 * backoff, capped). Calls onEvent for each JSON event and onStatus with
 * "connecting" | "open" | "closed".
 */
export function connectSessionWs(
  sessionId: string,
  onEvent: (event: WsEvent) => void,
  onStatus?: (status: "connecting" | "open" | "closed") => void,
): WsHandle {
  let ws: WebSocket | null = null;
  let closed = false;
  let attempts = 0;
  let timer: number | undefined;

  const url = `${window.location.protocol === "https:" ? "wss" : "ws"}://${
    window.location.host
  }${BASE}/sessions/${sessionId}/ws`;

  const connect = () => {
    if (closed) return;
    onStatus?.("connecting");
    ws = new WebSocket(url);
    ws.onopen = () => {
      attempts = 0;
      onStatus?.("open");
    };
    ws.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data as string) as WsEvent);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      onStatus?.("closed");
      if (!closed && attempts < 8) {
        attempts += 1;
        const delay = Math.min(500 * 2 ** attempts, 8000);
        timer = window.setTimeout(connect, delay);
      }
    };
    ws.onerror = () => {
      ws?.close();
    };
  };

  connect();
  return {
    close: () => {
      closed = true;
      if (timer !== undefined) window.clearTimeout(timer);
      ws?.close();
    },
  };
}
