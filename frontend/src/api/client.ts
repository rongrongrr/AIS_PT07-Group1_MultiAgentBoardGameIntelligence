const BASE = '/api';

/** Optional API key (the backend enforces one only when TILES_API_KEY is set). */
function apiKey(): string | null {
  try { return window.localStorage.getItem('tiles_api_key'); } catch { return null; }
}

async function request<T>(path: string, options?: RequestInit, retried = false): Promise<T> {
  const key = apiKey();
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(key ? { 'X-API-Key': key } : {}), ...(options?.headers || {}) },
  });
  if (res.status === 401 && !retried) {
    const entered = typeof window.prompt === 'function' ? window.prompt('This TILES server requires an API key:') : null;
    if (entered) {
      try { window.localStorage.setItem('tiles_api_key', entered); } catch { /* storage unavailable */ }
      return request<T>(path, options, true);
    }
  }
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// --- Types ---

export interface PlayerSlotConfig {
  slot: number;
  type: string;
  name?: string;
}

export interface SessionCreate {
  room_name: string;
  platform_url?: string;
  browser_mode: 'headless' | 'headed';
  players: PlayerSlotConfig[];
  move_timeout_sec?: number;
  stuck_abort_sec?: number;
}

export interface Session {
  id: string;
  room_name: string;
  platform_url: string;
  browser_mode: string;
  status: string;
  player_config: PlayerSlotConfig[];
  profiler_config: null | Record<string, unknown>;
  move_timeout_sec: number;
  stuck_abort_sec: number;
  final_scores: Record<string, number> | null;
  winner: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface GameAction {
  source_type: string;
  source_index: number | null;
  color: string;
  destination: string;
  destination_row: number | null;
}

export interface MoveResponse {
  step_id: number;
  player_name: string;
  system_tag: string | null;
  action: GameAction;
  decision_time_ms: number | null;
  timestamp: string;
  click_ms?: number;
  ws_wait_ms?: number;
  total_ms?: number;
  legal_actions?: number;
  commentary?: string | null;
  sessionId?: string;
  explanation?: {
    rationale?: string;
    model: string;
    chosen_score: number;
    n_legal: number;
    top_alternatives: { action: GameAction; score: number }[];
    adaptation?: { reason: string; playing_as: string; target_archetype?: string };
  } | null;
  round?: number;
  scores?: Record<string, number>;
  board?: {
    factories: string[][];
    center_pool: string[];
    players: {
      name: string;
      score: number;
      pattern_lines: string[][];
      wall: boolean[][];
      floor_line: string[];
    }[];
  };
}

export interface SysLogEntry {
  ts: string;
  level: string;
  player: string;
  phase: string;
  msg: string;
  data?: Record<string, unknown>;
}

export interface PlayerState {
  index: number;
  name: string;
  system_tag: string | null;
  score: number;
  pattern_lines: (string | null)[][];
  wall: boolean[][];
  floor_line: string[];
  has_first_player_token: boolean;
}

export interface GameStateData {
  timestamp: string;
  session_id: string | null;
  room_name: string;
  round: number;
  current_turn: string;
  factories: string[][];
  center_pool: string[];
  players: PlayerState[];
  game_over: boolean;
}

// --- API calls ---

export const api = {
  health: () => request<{ status: string }>('/health'),

  sessions: {
    list: () => request<Session[]>('/sessions'),
    get: (id: string) => request<Session>(`/sessions/${id}`),
    create: (data: SessionCreate) =>
      request<Session>('/sessions', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    start: (id: string) =>
      request<{ status: string; session_id: string; message: string }>(
        `/sessions/${id}/start`,
        { method: 'POST' }
      ),
    stop: (id: string) =>
      request<{ status: string }>(`/sessions/${id}/stop`, { method: 'POST' }),
  },

  players: {
    list: () => request<{ players: { name: string; type: string }[]; profilers: { name: string; type: string }[] }>('/players'),
  },

  history: {
    get: (sessionId: string) =>
      request<{ session_id: string; room_name: string; total_moves: number; moves: MoveResponse[] }>(
        `/history/${sessionId}`
      ),
    getState: (sessionId: string, step: number) =>
      request<{ state: GameStateData }>(`/history/${sessionId}/state/${step}`),
    exportGame: (sessionId: string) =>
      request<Record<string, unknown>>(`/history/${sessionId}/export`),
  },

  feedback: {
    submit: (body: {
      session_id: string; step_id: number; rater: string;
      understandable: number; useful: number; trustworthy: number; comment?: string;
    }) => request<{ id: number }>('/feedback', { method: 'POST', body: JSON.stringify(body) }),
    summary: () => request<Record<string, unknown>>('/feedback/summary'),
  },

  tournament: {
    latest: () => request<TournamentResults>('/tournament'),
  },

  profiler: {
    insights: (sessionId: string, uptoStep?: number) =>
      request<{ total_moves: number; analyzer: string; insights: PlayerInsight[] }>(
        `/profiler/${sessionId}/insights${uptoStep !== undefined ? `?upto_step=${uptoStep}` : ''}`
      ),
    listAnalyzers: () =>
      request<{ analyzers: { name: string; description: string }[] }>('/profiler/analyzers'),
    analyze: (sessionId: string, playerName: string, analyzerName = 'BasicProfileAnalyzer') =>
      request<Record<string, unknown>>(
        `/profiler/${sessionId}/analyze?player_name=${encodeURIComponent(playerName)}&analyzer_name=${encodeURIComponent(analyzerName)}`,
        { method: 'POST' }
      ),
  },
};

export interface PlayerInsight {
  player_name: string;
  moves_observed: number;
  style?: string | null;
  archetype?: string | null;
  archetype_confidence?: number | null;
  archetype_reasons?: { feature: string; meaning: string }[];
  summary: string;
}

export interface TournamentResults {
  available: boolean;
  generated?: string;
  games?: number;
  deals_per_pair?: number;
  ranking?: { player: string; elo: number; mean_score: number }[];
  win_rates?: Record<string, Record<string, number>>;
}

// --- WebSocket ---

export function connectSessionWs(
  sessionId: string,
  onMessage: (data: { type: string; data: unknown }) => void,
  onClose?: () => void
): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const key = apiKey();
  const ws = new WebSocket(`${protocol}//${window.location.host}/api/sessions/${sessionId}/ws${key ? `?api_key=${encodeURIComponent(key)}` : ''}`);

  ws.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data);
      onMessage(parsed);
    } catch {
      console.warn('Failed to parse WS message:', event.data);
    }
  };

  ws.onclose = () => onClose?.();
  ws.onerror = (e) => console.error('WS error:', e);

  return ws;
}
