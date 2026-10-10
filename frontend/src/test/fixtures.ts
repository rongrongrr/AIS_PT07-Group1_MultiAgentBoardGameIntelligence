import type {
  ActionDTO,
  AgentsDTO,
  AnalysisDTO,
  ExperimentRunDTO,
  GameStateDTO,
  HistoryResponse,
  PlayerProfileDTO,
  RoundResultDTO,
  SessionDetailDTO,
  SessionSummaryDTO,
  StatsDTO,
  TurnRecordDTO,
} from "../types";

export const action: ActionDTO = {
  source_type: "factory",
  source_index: 2,
  color: "red",
  destination: "pattern_line",
  destination_row: 3,
};

export const centerAction: ActionDTO = {
  source_type: "center",
  source_index: null,
  color: "blue",
  destination: "floor",
  destination_row: null,
};

export function makeState(overrides: Partial<GameStateDTO> = {}): GameStateDTO {
  return {
    num_players: 2,
    round: 2,
    phase: "drafting",
    current_player: 0,
    factories: [["red", "blue"], []],
    center_pool: ["blue", "firstPlayer"],
    bag: [5, 5, 5, 5, 5],
    lid: [1, 0, 0, 0, 0],
    players: [
      {
        name: "Ada",
        score: 7,
        wall: [[true, false, false, false, false], [], [], [], []],
        pattern_lines: [["blue"], [], ["red", "red"], [], []],
        floor_line: ["red", "red", "red", "red", "red", "red", "red", "red"],
        has_first_player_token: true,
      },
      {
        name: "",
        score: 3,
        wall: [],
        pattern_lines: [[], [], [], [], []],
        floor_line: [],
        has_first_player_token: false,
      },
    ],
    ...overrides,
  };
}

export const profile: PlayerProfileDTO = {
  player_index: 1,
  player_name: "Bob",
  archetype: "floor_dumper",
  confidence: 0.72,
  traits: { aggression: 0.5, tempo_ms: 12, greed: 1.4 },
  moves_observed: 9,
  summary: "Likes the floor.",
};

export function makeRecord(overrides: Partial<TurnRecordDTO> = {}): TurnRecordDTO {
  return {
    step: 1,
    round: 1,
    player_index: 0,
    player_name: "Ada",
    tactician: "mcts_profiled",
    action,
    state_before: makeState(),
    state_after: makeState(),
    explanation: { text: "Takes red.", concepts: ["floor_avoidance"], evidence: {} },
    report: {
      candidates: [
        {
          action,
          score: 1.5,
          visits: 10,
          prior: 0.3,
          principal_variation: [action, centerAction],
          notes: {},
        },
        { action: centerAction, score: 0.5, visits: 0, prior: 0, principal_variation: [], notes: {} },
      ],
      simulations: 200,
      elapsed_ms: 5,
      used_opponent_model: true,
      notes: {},
    },
    profiles: { "1": profile },
    validation: { ok: true, violation: null, attempts: 2, site_fallback: true },
    timing: { decide_ms: 1.234, validate_ms: 0.5, execute_ms: 100, explain_ms: 0.2, total_ms: 102 },
    ...overrides,
  };
}

export const round: RoundResultDTO = {
  round: 1,
  tilings: [{ player_index: 0, row: 1, col: 2, color: "red", points: 3 }],
  floor_penalties: [-2, 0],
  scores: [4, 0],
  game_over: true,
  bonuses: null,
};

export function makeSession(overrides: Partial<SessionSummaryDTO> = {}): SessionSummaryDTO {
  return {
    id: "s1",
    mode: "local",
    status: "completed",
    players: [
      { name: "Ada", tactician: "greedy" },
      { name: "Bob", tactician: "mcts" },
    ],
    created_at: "2026-01-02T03:04:05Z",
    steps: 12,
    scores: [10, 8],
    winner_name: "Ada",
    ...overrides,
  };
}

export function makeDetail(overrides: Partial<SessionDetailDTO> = {}): SessionDetailDTO {
  return { ...makeSession(), state: makeState(), ...overrides };
}

export const history: HistoryResponse = {
  session: makeSession(),
  moves: [
    makeRecord({ step: 1, round: 1 }),
    makeRecord({ step: 2, round: 1, player_index: 1, player_name: "Bob" }),
    makeRecord({ step: 3, round: 2 }),
  ],
  rounds: [round],
};

export const agents: AgentsDTO = {
  tacticians: [
    {
      name: "greedy",
      class: "GreedyTactician",
      description: "Picks the best immediate move.",
      params: [
        { name: "noise", type: "float", default: 0.1, min: 0, max: 1, description: "Randomness" },
        { name: "depth", type: "int", default: 2 },
      ],
    },
    { name: "mcts_profiled", uses_opponent_model: true, params: [] },
    { name: "human", params: [] },
  ],
  profilers: [{ name: "basic", description: "x".repeat(100) }],
  explainers: [
    { name: "template" },
    { name: "llm", requires: "ANTHROPIC_API_KEY", description: "Uses Claude" },
  ],
  validator: { name: "validator", description: "Rules" },
};

export const stats: StatsDTO = {
  sessions: { total: 3, by_status: { completed: 2, running: 1 }, by_mode: { live: 1 } },
  moves_total: 1234,
  experiments: { total: 1, by_status: { completed: 1 } },
  tacticians: [
    { name: "mcts", games: 4, wins: 3, win_rate: 0.75, avg_score: 30.5, avg_decide_ms: 12.3 },
    { name: "greedy", games: 4, wins: 1, win_rate: 0.25 },
  ],
  archetypes: { floor_dumper: 3, builder: 1 },
  latency: { decide_ms: { p50: 1.2, p90: 3, max: 9 }, validate_ms: {} },
  recent_sessions: [makeSession()],
};

export const analysis: AnalysisDTO = {
  session_id: "s1",
  profiler: "basic",
  moves_analyzed: 20,
  players: [
    {
      player_index: 0,
      player_name: "Ada",
      tactician: "greedy",
      profile: { ...profile, player_index: 0, player_name: "Ada" },
      stats: {
        moves: 10,
        final_score: 22,
        color_distribution: { blue: 4, red: 6 },
        source_split: { factory: 8, center: 2 },
        destination_split: { pattern_line: 9, floor: 1 },
        row_preferences: { "0": 2, "2": 5 },
        floor_rate: 0.1,
        completion_rate: 0.5,
        avg_decision_ms: 2,
        avg_legal_actions: 14,
        score_trajectory: [0, 2, 5],
        concepts: { floor_avoidance: 3 },
      },
      timeline: [
        { step: 1, archetype: "builder", confidence: 0.4 },
        { step: 2, archetype: "builder", confidence: 0.5 },
        { step: 3, archetype: "builder", confidence: 0.6 },
        { step: 4, archetype: "floor_dumper", confidence: 0.6 },
      ],
    },
    {
      player_index: 1,
      player_name: "Bob",
      tactician: null,
      profile: profile,
      stats: {
        moves: 0,
        final_score: 0,
        color_distribution: {},
        source_split: {},
        destination_split: {},
        row_preferences: {},
        floor_rate: 0,
        completion_rate: 0,
        avg_decision_ms: 0,
        score_trajectory: [],
        concepts: {},
      },
      timeline: [],
    },
  ],
};

export function makeRun(overrides: Partial<ExperimentRunDTO> = {}): ExperimentRunDTO {
  return {
    id: "e1",
    kind: "tournament",
    title: "Tournament",
    params: { games: 4, flag: true },
    status: "completed",
    created_at: "2026-01-02T03:04:05Z",
    completed_at: "2026-01-02T03:05:05Z",
    progress: { done: 4, total: 4, message: "done" },
    result: {
      summary: "Mcts wins.",
      metrics: { win_rate: 0.75 },
      tables: [{ title: "Table", columns: ["name", "value"], rows: [["a", 1.5], ["b", null], ["c", true], ["d", false]] }],
      series: [
        { title: "Bars", kind: "bar", labels: ["a", "b"], data: [{ name: "s", values: [1, 2] }] },
      ],
      raw: { a: 1 },
    },
    ...overrides,
  };
}
