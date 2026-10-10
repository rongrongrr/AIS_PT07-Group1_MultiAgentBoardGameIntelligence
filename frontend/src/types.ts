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
}

export interface TimingDTO {
  decide_ms?: number;
  validate_ms?: number;
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

export interface PlayerSlot {
  name: string;
  tactician: string;
  config?: Record<string, unknown>;
}

export interface SessionSummaryDTO {
  id: string;
  status: string;
  mode: string;
  players: PlayerSlot[];
  created_at?: string;
  scores?: number[] | null;
}

export interface LiveConfigDTO {
  room_name?: string;
  platform_url?: string;
  headless?: boolean;
}

export interface SessionDetailDTO extends SessionSummaryDTO {
  state?: GameStateDTO | null;
  profiler?: string | null;
  explainer?: string | null;
  seed?: number | null;
  move_delay_ms?: number;
  live?: LiveConfigDTO | null;
  room_url?: string | null;
  winner?: number | null;
}

export interface TacticianInfoDTO {
  name: string;
  uses_opponent_model?: boolean;
  description?: string;
  class?: string;
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
  session: SessionDetailDTO;
  moves: TurnRecordDTO[];
}

export type WsEvent =
  | { type: "status"; status: string }
  | { type: "state"; step: number; state: GameStateDTO }
  | { type: "move"; step: number; record: TurnRecordDTO }
  | { type: "round"; round: number; result: Record<string, unknown> }
  | {
      type: "game_over";
      winner: number;
      scores: number[];
      bonuses?: unknown[];
    }
  | { type: "log"; level: string; message: string };

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
