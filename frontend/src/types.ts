/** DTOs mirroring docs/API.md and the backend's to_dict() serializers. */

export type ColorName = "blue" | "yellow" | "red" | "black" | "white";
export type TileName = ColorName | "firstPlayer";

export const COLOR_ORDER: ColorName[] = [
  "blue",
  "yellow",
  "red",
  "black",
  "white",
];

/** Standard Azul wall: color that belongs at (row, col). */
export function wallColorAt(row: number, col: number): ColorName {
  return COLOR_ORDER[(((col - row) % 5) + 5) % 5];
}

export const FLOOR_PENALTIES = [-1, -1, -2, -2, -2, -3, -3];

// ---------------------------------------------------------------------------
// Game state / decisions
// ---------------------------------------------------------------------------

export interface PlayerBoardDTO {
  name: string;
  score: number;
  wall: boolean[][];
  pattern_lines: TileName[][];
  floor_line: TileName[];
  has_first_player_token: boolean;
}

export interface GameStateDTO {
  num_players: number;
  round: number;
  phase: string;
  current_player: number;
  factories: ColorName[][];
  center_pool: TileName[];
  bag: number[];
  lid: number[];
  players: PlayerBoardDTO[];
}

export interface ActionDTO {
  source_type: "factory" | "center";
  source_index: number | null;
  color: ColorName;
  destination: "pattern_line" | "floor";
  destination_row: number | null;
}

export interface CandidateDTO {
  action: ActionDTO;
  score: number;
  visits: number;
  prior: number;
  principal_variation: ActionDTO[];
  notes: Record<string, number>;
}

export interface SearchReportDTO {
  candidates: CandidateDTO[];
  simulations: number;
  elapsed_ms: number;
  used_opponent_model: boolean;
  notes: Record<string, unknown>;
}

export interface ExplanationDTO {
  text: string;
  concepts: string[];
  evidence: Record<string, unknown>;
}

export interface PlayerProfileDTO {
  player_index: number;
  player_name: string;
  archetype: string;
  confidence: number;
  traits: Record<string, number>;
  moves_observed: number;
  summary: string;
}

export interface ValidationDTO {
  ok: boolean;
  violation: { predicate: string; message: string } | null;
  attempts?: number;
  site_fallback?: boolean;
}

export interface TimingDTO {
  decide_ms?: number;
  validate_ms?: number;
  execute_ms?: number;
  explain_ms?: number;
  total_ms?: number;
}

export interface TurnRecordDTO {
  step: number;
  round: number;
  player_index: number;
  player_name: string;
  tactician: string;
  action: ActionDTO;
  state_before?: GameStateDTO | null;
  state_after?: GameStateDTO | null;
  explanation?: ExplanationDTO | null;
  report?: SearchReportDTO | null;
  profiles?: Record<string, PlayerProfileDTO> | null;
  validation?: ValidationDTO | null;
  timing?: TimingDTO | null;
}

export interface TilingDTO {
  player_index: number;
  row: number;
  col: number;
  color: ColorName;
  points: number;
}

export interface RoundResultDTO {
  round: number;
  tilings: TilingDTO[];
  floor_penalties: number[];
  scores: number[];
  game_over: boolean;
  bonuses: unknown;
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export interface PlayerSlot {
  name: string;
  tactician: string;
  config?: Record<string, unknown>;
}

export interface LiveConfigDTO {
  room_name?: string;
  platform_url?: string;
  headless?: boolean;
}

export type SessionStatus =
  | "created"
  | "connecting"
  | "lobby"
  | "running"
  | "completed"
  | "aborted"
  | "failed"
  | "stalled"
  | string;

export interface SessionSummaryDTO {
  id: string;
  mode: "local" | "live" | string;
  status: SessionStatus;
  players: PlayerSlot[];
  profiler?: string | null;
  explainer?: string | null;
  seed?: number | null;
  created_at?: string | null;
  completed_at?: string | null;
  scores?: number[] | null;
  winner?: number | null;
  winner_name?: string | null;
  steps?: number | null;
  rounds?: number | null;
  room_url?: string | null;
  room_name?: string | null;
}

export interface SessionResultDTO {
  scores: number[];
  winner: number;
  steps: number;
  duration_s?: number;
}

export interface SessionDetailDTO extends SessionSummaryDTO {
  state?: GameStateDTO | null;
  result?: SessionResultDTO | null;
  move_delay_ms?: number;
  live?: LiveConfigDTO | null;
  error?: string | null;
}

export interface CreateSessionRequest {
  mode: "local" | "live";
  players: PlayerSlot[];
  profiler: string | null;
  explainer: string | null;
  seed?: number | null;
  move_delay_ms?: number;
  live?: LiveConfigDTO;
}

export interface HistoryResponse {
  session: SessionSummaryDTO;
  moves: TurnRecordDTO[];
  rounds?: RoundResultDTO[];
}

export type WsEvent =
  | {
      type: "status";
      status: string;
      room_url?: string;
      room_name?: string;
      waiting_for_humans?: string[];
    }
  | { type: "state"; step: number; state: GameStateDTO }
  | { type: "move"; step: number; record: TurnRecordDTO }
  | { type: "round"; round: number; result: RoundResultDTO }
  | {
      type: "game_over";
      winner: number;
      scores: number[];
      bonuses?: unknown;
    }
  | {
      type: "log";
      level: string;
      message: string;
      phase?: string;
      player?: string;
    };

export interface LogEntry {
  ts: string;
  level: string;
  message: string;
  phase?: string;
  player?: string;
}

// ---------------------------------------------------------------------------
// Health / agents
// ---------------------------------------------------------------------------

export interface HealthDTO {
  status: string;
  version: string;
  live_available?: boolean;
  llm_available?: boolean;
}

export interface ParamSpecDTO {
  name: string;
  type: "int" | "float" | "str" | "bool" | "choice" | string;
  default?: unknown;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  description?: string;
  choices?: string[];
}

export interface AgentInfoDTO {
  name: string;
  class?: string;
  description?: string;
  uses_opponent_model?: boolean | null;
  params?: ParamSpecDTO[];
  requires?: string | null;
}

export interface AgentsDTO {
  tacticians: AgentInfoDTO[];
  profilers: AgentInfoDTO[];
  explainers: AgentInfoDTO[];
  validator?: AgentInfoDTO | null;
}

// ---------------------------------------------------------------------------
// Profiles
// ---------------------------------------------------------------------------

export interface ArchetypeDTO {
  name: string;
  description: string;
  signature: Record<string, number>;
}

export interface PlayerStatsDTO {
  moves: number;
  final_score: number;
  color_distribution: Record<string, number>;
  source_split: Record<string, number>;
  destination_split: Record<string, number>;
  row_preferences: Record<string, number>;
  floor_rate: number;
  completion_rate: number;
  avg_decision_ms: number;
  avg_legal_actions?: number;
  score_trajectory: number[];
  concepts: Record<string, number>;
}

export interface TimelinePointDTO {
  step: number;
  archetype: string;
  confidence: number;
  traits?: Record<string, number>;
}

export interface PlayerAnalysisDTO {
  player_index: number;
  player_name: string;
  tactician?: string | null;
  profile: PlayerProfileDTO;
  stats: PlayerStatsDTO;
  timeline: TimelinePointDTO[];
}

export interface AnalysisDTO {
  session_id: string;
  profiler: string;
  moves_analyzed: number;
  players: PlayerAnalysisDTO[];
}

// ---------------------------------------------------------------------------
// Experiments
// ---------------------------------------------------------------------------

export interface ExperimentTypeDTO {
  name: string;
  title: string;
  description?: string;
  report_section?: string;
  estimated?: string;
  params: ParamSpecDTO[];
}

export type CellValue = string | number | boolean | null;

export interface TableDTO {
  title: string;
  columns: string[];
  rows: CellValue[][];
}

export interface SeriesDataDTO {
  name: string;
  values: (number | null)[];
}

export interface SeriesDTO {
  title: string;
  kind: "bar" | "line" | "matrix" | string;
  x_label?: string;
  y_label?: string;
  labels: string[];
  row_labels?: string[];
  data: SeriesDataDTO[];
}

export interface ExperimentResultDTO {
  summary: string;
  metrics: Record<string, number>;
  tables: TableDTO[];
  series: SeriesDTO[];
  raw?: unknown;
}

export interface ExperimentProgressDTO {
  done: number;
  total: number;
  message?: string;
}

export type ExperimentStatus =
  | "created"
  | "running"
  | "completed"
  | "failed"
  | "aborted"
  | string;

export interface ExperimentRunDTO {
  id: string;
  kind: string;
  title: string;
  params: Record<string, unknown>;
  status: ExperimentStatus;
  created_at?: string | null;
  completed_at?: string | null;
  progress?: ExperimentProgressDTO | null;
  error?: string | null;
  result?: ExperimentResultDTO | null;
}

export type ExperimentWsEvent =
  | { type: "status"; status: string }
  | { type: "progress"; done: number; total: number; message?: string }
  | { type: "log"; level: string; message: string }
  | { type: "result"; result: ExperimentResultDTO };

// ---------------------------------------------------------------------------
// Rulebook
// ---------------------------------------------------------------------------

export interface RulebookSectionDTO {
  id: string;
  title: string;
  text: string;
}

export interface RulebookDTO {
  sections: RulebookSectionDTO[];
}

export interface RulebookSearchResultDTO {
  section: string;
  text: string;
  score: number;
}

export interface RulebookSearchDTO {
  query: string;
  results: RulebookSearchResultDTO[];
}

export interface RuleSpecDTO {
  id: string;
  section: string;
  kind: string;
  predicate: string | null;
  parameters: Record<string, unknown>;
  text: string;
  status: "verified" | "mismatch" | "skipped" | string;
  detail?: string;
}

export interface RulesDTO {
  extractor: string;
  accuracy: number;
  verified: number;
  checked: number;
  skipped: number;
  rules: RuleSpecDTO[];
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

export interface LatencyStatDTO {
  p50?: number;
  p90?: number;
  max?: number;
}

export interface TacticianStatDTO {
  name: string;
  games: number;
  wins: number;
  win_rate: number;
  avg_score?: number;
  avg_decide_ms?: number;
}

export interface StatsDTO {
  sessions: {
    total: number;
    by_status: Record<string, number>;
    by_mode: Record<string, number>;
  };
  moves_total: number;
  experiments: { total: number; by_status: Record<string, number> };
  tacticians: TacticianStatDTO[];
  archetypes: Record<string, number>;
  latency: Record<string, LatencyStatDTO>;
  recent_sessions: SessionSummaryDTO[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Compact human label for an action, e.g. "red: factory 3 → row 4". */
export function describeAction(a: ActionDTO): string {
  const src =
    a.source_type === "center"
      ? "center"
      : `factory ${(a.source_index ?? 0) + 1}`;
  const dst =
    a.destination === "floor" ? "floor" : `row ${(a.destination_row ?? 0) + 1}`;
  return `${a.color}: ${src} → ${dst}`;
}

export function sameAction(a: ActionDTO, b: ActionDTO): boolean {
  return (
    a.source_type === b.source_type &&
    (a.source_index ?? null) === (b.source_index ?? null) &&
    a.color === b.color &&
    a.destination === b.destination &&
    (a.destination_row ?? null) === (b.destination_row ?? null)
  );
}

export function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(start?: string | null, end?: string | null): string {
  if (!start) return "";
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const sec = Math.max(0, Math.round((e - s) / 1000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

export function formatNumber(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toFixed(digits);
}

export function formatPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${Math.round(n * 100)}%`;
}

export function playersLabel(players: PlayerSlot[]): string {
  return players.map((p) => `${p.name} (${p.tactician})`).join(" vs ");
}
