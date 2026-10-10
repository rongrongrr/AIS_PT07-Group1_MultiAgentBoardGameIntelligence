import type {
  AgentsDTO,
  AnalysisDTO,
  ArchetypeDTO,
  CreateSessionRequest,
  ExperimentRunDTO,
  ExperimentTypeDTO,
  ExperimentWsEvent,
  HealthDTO,
  HistoryResponse,
  PlayerProfileDTO,
  RulebookDTO,
  RulebookSearchDTO,
  RulesDTO,
  SessionDetailDTO,
  SessionSummaryDTO,
  StatsDTO,
  AgentInfoDTO,
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
      const body = (await res.json()) as { detail?: unknown };
      detail =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthDTO>("/health"),

  agents: () => request<AgentsDTO>("/agents"),
  listTacticians: () => request<AgentInfoDTO[]>("/tacticians"),

  // -- sessions ------------------------------------------------------------
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
  deleteSession: (id: string) =>
    request<{ deleted: string }>(`/sessions/${id}`, { method: "DELETE" }),

  // -- history -------------------------------------------------------------
  getHistory: (id: string) => request<HistoryResponse>(`/history/${id}`),
  exportUrl: (id: string) => `${BASE}/history/${id}/export`,

  // -- profiles ------------------------------------------------------------
  getProfiles: (id: string) =>
    request<{ profiles: PlayerProfileDTO[] }>(`/profiles/${id}`),
  archetypes: () => request<ArchetypeDTO[]>("/profiles/archetypes"),
  analyzeSession: (id: string, profiler: string) =>
    request<AnalysisDTO>(
      `/profiles/${id}/analyze?profiler=${encodeURIComponent(profiler)}`,
      { method: "POST" },
    ),

  // -- experiments ---------------------------------------------------------
  experimentTypes: () => request<ExperimentTypeDTO[]>("/experiments/types"),
  listExperiments: () => request<ExperimentRunDTO[]>("/experiments"),
  getExperiment: (id: string) => request<ExperimentRunDTO>(`/experiments/${id}`),
  startExperiment: (kind: string, params: Record<string, unknown>) =>
    request<ExperimentRunDTO>("/experiments", {
      method: "POST",
      body: JSON.stringify({ kind, params }),
    }),
  stopExperiment: (id: string) =>
    request<{ status: string }>(`/experiments/${id}/stop`, { method: "POST" }),
  deleteExperiment: (id: string) =>
    request<{ deleted: string }>(`/experiments/${id}`, { method: "DELETE" }),

  // -- rulebook ------------------------------------------------------------
  rulebook: () => request<RulebookDTO>("/rulebook"),
  rulebookSearch: (q: string, k = 5) =>
    request<RulebookSearchDTO>(
      `/rulebook/search?q=${encodeURIComponent(q)}&k=${k}`,
    ),
  rules: (extractor?: string) =>
    request<RulesDTO>(
      `/rulebook/rules${extractor ? `?extractor=${encodeURIComponent(extractor)}` : ""}`,
    ),

  // -- stats ---------------------------------------------------------------
  stats: () => request<StatsDTO>("/stats"),
};

export interface WsHandle {
  close: () => void;
}

export type WsStatus = "connecting" | "open" | "closed";

/**
 * Open a WebSocket with automatic reconnect (exponential backoff, capped
 * at 8 attempts). Calls onEvent for each JSON frame and onStatus on
 * state changes.
 */
function connectWs<E>(
  path: string,
  onEvent: (event: E) => void,
  onStatus?: (status: WsStatus) => void,
): WsHandle {
  let ws: WebSocket | null = null;
  let closed = false;
  let attempts = 0;
  let timer: number | undefined;

  const url = `${window.location.protocol === "https:" ? "wss" : "ws"}://${
    window.location.host
  }${BASE}${path}`;

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
        onEvent(JSON.parse(msg.data as string) as E);
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

export function connectSessionWs(
  sessionId: string,
  onEvent: (event: WsEvent) => void,
  onStatus?: (status: WsStatus) => void,
): WsHandle {
  return connectWs<WsEvent>(`/sessions/${sessionId}/ws`, onEvent, onStatus);
}

export function connectExperimentWs(
  experimentId: string,
  onEvent: (event: ExperimentWsEvent) => void,
  onStatus?: (status: WsStatus) => void,
): WsHandle {
  return connectWs<ExperimentWsEvent>(
    `/experiments/${experimentId}/ws`,
    onEvent,
    onStatus,
  );
}

/** Trigger a browser download of a JSON document. */
export function downloadJson(name: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
