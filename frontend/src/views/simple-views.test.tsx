import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Agents } from "./Agents";
import { Dashboard } from "./Dashboard";
import { Rulebook } from "./Rulebook";
import App from "../App";
import { agents, makeRun, stats } from "../test/fixtures";

const mocks = vi.hoisted(() => ({
  api: {
    health: vi.fn(),
    agents: vi.fn(),
    stats: vi.fn(),
    rulebook: vi.fn(),
    rules: vi.fn(),
    rulebookSearch: vi.fn(),
    listSessions: vi.fn(),
    experimentTypes: vi.fn(),
    listExperiments: vi.fn(),
    archetypes: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({
  api: mocks.api,
  connectSessionWs: vi.fn(() => ({ close: vi.fn() })),
  connectExperimentWs: vi.fn(() => ({ close: vi.fn() })),
  downloadJson: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.location.hash = "";
});

describe("Dashboard", () => {
  it("shows an error when the backend is unreachable", async () => {
    mocks.api.stats.mockRejectedValue(new Error("down"));
    render(<Dashboard />);
    expect(await screen.findByText(/Backend unreachable: down/)).toBeInTheDocument();
  });

  it("shows loading first", () => {
    mocks.api.stats.mockReturnValue(new Promise(() => undefined));
    render(<Dashboard />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders statistics with proper casing", async () => {
    mocks.api.stats.mockResolvedValue(stats);
    render(<Dashboard />);
    expect(await screen.findByText("Win rate by tactician")).toBeInTheDocument();
    expect(screen.getAllByText("MCTS").length).toBeGreaterThan(0);
    expect(screen.getByText("Avg Score")).toBeInTheDocument();
    expect(screen.getByText("Decide")).toBeInTheDocument();
    expect(screen.getByText("Recent sessions")).toBeInTheDocument();
    expect(screen.getByText("2 completed")).toBeInTheDocument();
  });

  it("shows an empty state for a fresh install", async () => {
    mocks.api.stats.mockResolvedValue({
      ...stats,
      sessions: { total: 0, by_status: {}, by_mode: {} },
      recent_sessions: [],
    });
    render(<Dashboard />);
    expect(await screen.findByText(/No games recorded yet/)).toBeInTheDocument();
  });

  it("handles missing tactician and archetype data", async () => {
    mocks.api.stats.mockResolvedValue({ ...stats, tacticians: [], archetypes: {}, latency: {}, recent_sessions: [] });
    render(<Dashboard />);
    expect(await screen.findByText("No finished games yet.")).toBeInTheDocument();
    expect(screen.getByText(/Run a session with the Profiler enabled/)).toBeInTheDocument();
  });
});

describe("Agents", () => {
  it("renders the pipeline and agent catalogue", async () => {
    mocks.api.agents.mockResolvedValue(agents);
    render(<Agents />);
    expect(screen.getByRole("img", { name: /Decision Stack turn pipeline/ })).toBeInTheDocument();
    expect(await screen.findByText("Greedy")).toBeInTheDocument();
    expect(screen.getByText("MCTS Profiled")).toBeInTheDocument();
    expect(screen.getByText("Needs ANTHROPIC_API_KEY")).toBeInTheDocument();
    expect(screen.getByText("Opponent-Aware")).toBeInTheDocument();
    expect(screen.getByText("Validator", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByText("Range")).toBeInTheDocument();
  });

  it("omits the validator when absent and reports errors", async () => {
    mocks.api.agents.mockResolvedValueOnce({ ...agents, validator: null });
    const { unmount } = render(<Agents />);
    await screen.findByText("Greedy");
    expect(screen.queryByText("Validator", { selector: "h3" })).toBeNull();
    unmount();
    mocks.api.agents.mockRejectedValueOnce(new Error("nope"));
    render(<Agents />);
    expect(await screen.findByText(/Backend unreachable: nope/)).toBeInTheDocument();
  });
});

describe("Rulebook", () => {
  const book = {
    sections: [
      { id: "1", title: "Setup", text: "Set up the game." },
      { id: "2", title: "Scoring", text: "Score points." },
    ],
  };
  const rules = {
    extractor: "deterministic",
    accuracy: 0.9,
    verified: 9,
    checked: 10,
    skipped: 1,
    rules: [
      { id: "r1", section: "1", kind: "wall_rule", predicate: "p", parameters: { a: 1 }, text: "t", status: "verified" },
      { id: "r2", section: "2", kind: "floor", predicate: null, parameters: {}, text: "t", status: "mismatch", detail: "bad" },
    ],
  };

  beforeEach(() => {
    mocks.api.rulebook.mockResolvedValue(book);
    mocks.api.rules.mockResolvedValue(rules);
  });

  it("browses sections and shows extracted rules", async () => {
    render(<Rulebook />);
    expect(await screen.findByText("Set up the game.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Scoring" }));
    expect(screen.getByText("Score points.")).toBeInTheDocument();
    expect(await screen.findByText("Wall Rule")).toBeInTheDocument();
    expect(screen.getByText("Mismatch")).toBeInTheDocument();
    expect(screen.getByText("bad")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
  });

  it("searches the rulebook", async () => {
    mocks.api.rulebookSearch.mockResolvedValue({
      query: "q",
      results: [{ section: "2", text: "Floor passage", score: 0.5 }],
    });
    render(<Rulebook />);
    const input = screen.getByPlaceholderText(/What happens/);
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(mocks.api.rulebookSearch).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: " floor " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByText("Floor passage")).toBeInTheDocument();
    expect(mocks.api.rulebookSearch).toHaveBeenCalledWith("floor", 6);
    fireEvent.click(screen.getByRole("button", { name: "§2" }));
  });

  it("shows empty search results", async () => {
    mocks.api.rulebookSearch.mockResolvedValue({ query: "q", results: [] });
    render(<Rulebook />);
    fireEvent.change(screen.getByPlaceholderText(/What happens/), { target: { value: "zzz" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No matching passages.")).toBeInTheDocument();
  });

  it("switches the extractor and reports errors", async () => {
    render(<Rulebook />);
    await screen.findByText("Wall Rule");
    mocks.api.rules.mockRejectedValue(new Error("llm unavailable"));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "llm" } });
    expect(await screen.findByText("llm unavailable")).toBeInTheDocument();
    expect(mocks.api.rules).toHaveBeenLastCalledWith("llm");
  });

  it("reports an unreachable backend", async () => {
    mocks.api.rulebook.mockRejectedValue(new Error("down"));
    render(<Rulebook />);
    expect(await screen.findByText(/Backend unreachable: down/)).toBeInTheDocument();
  });
});

describe("App", () => {
  beforeEach(() => {
    mocks.api.health.mockResolvedValue({ status: "ok", version: "1.2", live_available: false, llm_available: false });
    mocks.api.stats.mockResolvedValue(stats);
    mocks.api.agents.mockResolvedValue(agents);
    mocks.api.rulebook.mockResolvedValue({ sections: [] });
    mocks.api.rules.mockResolvedValue({ extractor: "x", accuracy: 0, verified: 0, checked: 0, skipped: 0, rules: [] });
    mocks.api.listSessions.mockResolvedValue([]);
    mocks.api.archetypes.mockResolvedValue([]);
    mocks.api.experimentTypes.mockResolvedValue([]);
    mocks.api.listExperiments.mockResolvedValue([makeRun()]);
  });

  it("shows navigation, branding and capability badges", async () => {
    render(<App />);
    expect(screen.getByText("TILES")).toBeInTheDocument();
    expect(screen.getByText("Explainable Multi-Agent Azul")).toBeInTheDocument();
    expect(await screen.findByText("No Live")).toBeInTheDocument();
    expect(screen.getByText("No LLM")).toBeInTheDocument();
    expect(screen.getByTitle("Backend OK · v1.2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveClass("nav-item-active");
  });

  it("routes between views", async () => {
    window.location.hash = "#/agents";
    render(<App />);
    expect(await screen.findByText("The Decision Stack")).toBeInTheDocument();
    window.location.hash = "#/rulebook";
    fireEvent(window, new HashChangeEvent("hashchange"));
    expect(await screen.findByText("Ask the rulebook")).toBeInTheDocument();
    for (const hash of ["#/sessions", "#/monitor", "#/replay", "#/profiles", "#/experiments"]) {
      window.location.hash = hash;
      fireEvent(window, new HashChangeEvent("hashchange"));
    }
    await waitFor(() => expect(screen.getByRole("link", { name: "Experiments" })).toHaveClass("nav-item-active"));
  });

  it("flags an unreachable backend", async () => {
    mocks.api.health.mockRejectedValue(new Error("down"));
    render(<App />);
    expect(await screen.findByTitle(/Backend unreachable/)).toBeInTheDocument();
  });
});
