import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Monitor } from "./Monitor";
import { Profiles } from "./Profiles";
import { Replay } from "./Replay";
import { Sessions } from "./Sessions";
import type { WsEvent } from "../types";
import {
  agents,
  analysis,
  history,
  makeDetail,
  makeRecord,
  makeSession,
  makeState,
  round,
} from "../test/fixtures";

const mocks = vi.hoisted(() => ({
  api: {
    agents: vi.fn(),
    listSessions: vi.fn(),
    getSession: vi.fn(),
    getHistory: vi.fn(),
    createSession: vi.fn(),
    startSession: vi.fn(),
    stopSession: vi.fn(),
    deleteSession: vi.fn(),
    analyzeSession: vi.fn(),
    archetypes: vi.fn(),
    exportUrl: (id: string) => `/api/history/${id}/export`,
  },
  ws: {
    handler: null as ((e: WsEvent) => void) | null,
    status: null as ((s: "connecting" | "open" | "closed") => void) | null,
    close: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({
  api: mocks.api,
  connectSessionWs: vi.fn((_id: string, onEvent: (e: WsEvent) => void, onStatus: (s: "connecting" | "open" | "closed") => void) => {
    mocks.ws.handler = onEvent;
    mocks.ws.status = onStatus;
    return { close: mocks.ws.close };
  }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  mocks.api.agents.mockResolvedValue(agents);
  mocks.api.listSessions.mockResolvedValue([makeSession(), makeSession({ id: "s2", status: "running" })]);
  mocks.api.getSession.mockResolvedValue(makeDetail());
  mocks.api.getHistory.mockResolvedValue(history);
  mocks.api.archetypes.mockResolvedValue([{ name: "floor_dumper", description: "Dumps tiles", signature: {} }]);
  mocks.api.createSession.mockResolvedValue(makeDetail({ id: "new1" }));
  mocks.api.startSession.mockResolvedValue({ status: "running" });
  mocks.api.stopSession.mockResolvedValue({ status: "stopped" });
  mocks.api.deleteSession.mockResolvedValue({ deleted: "s1" });
  mocks.api.analyzeSession.mockResolvedValue(analysis);
});

const emit = (event: WsEvent) => act(() => mocks.ws.handler?.(event));

describe("Monitor", () => {
  it("lists sessions when none is selected", async () => {
    render(<Monitor sessionId={null} />);
    expect(await screen.findByText("Monitor a session")).toBeInTheDocument();
    expect((await screen.findAllByText("Replay")).length).toBe(2);
  });

  it("explains an empty or failing session list", async () => {
    mocks.api.listSessions.mockResolvedValueOnce([]);
    const { unmount } = render(<Monitor sessionId={null} />);
    expect(await screen.findByText(/No sessions yet/)).toBeInTheDocument();
    unmount();
    mocks.api.listSessions.mockRejectedValueOnce(new Error("down"));
    render(<Monitor sessionId={null} />);
    expect(await screen.findByText(/Backend unreachable: down/)).toBeInTheDocument();
  });

  it("shows a finished game from the API", async () => {
    mocks.api.getSession.mockResolvedValue(
      makeDetail({ result: { scores: [10, 8], winner: 0, steps: 3 } }),
    );
    render(<Monitor sessionId="s1" />);
    expect(await screen.findByText(/Ada wins/)).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Move log")).toBeInTheDocument();
    expect(screen.getByText("Export JSON")).toHaveAttribute("href", "/api/history/s1/export");
  });

  it("reflects live socket events", async () => {
    mocks.api.getSession.mockResolvedValue(
      makeDetail({ status: "running", mode: "live", room_name: "room-1", room_url: "http://x", state: null }),
    );
    mocks.api.getHistory.mockResolvedValue({ ...history, moves: [], rounds: undefined });
    render(<Monitor sessionId="s1" />);
    expect(await screen.findByText("Live platform")).toBeInTheDocument();
    expect(screen.getByText("Join link ↗")).toBeInTheDocument();
    expect(screen.getByText(/Humans: open the link/)).toBeInTheDocument();
    expect(screen.getByText("Polling")).toBeInTheDocument();

    act(() => mocks.ws.status?.("open"));
    expect(screen.queryByText("Polling")).toBeNull();

    await emit({ type: "status", status: "lobby", room_url: "http://y", room_name: "r2", waiting_for_humans: ["Zed"] });
    expect(screen.getByText(/Waiting for: Zed/)).toBeInTheDocument();

    await emit({ type: "state", step: 1, state: makeState() });
    expect(screen.getByText("Round 2", { selector: ".muted" })).toBeInTheDocument();

    await emit({ type: "move", step: 1, record: makeRecord() });
    expect(screen.getAllByText("Red: Factory 3 → Row 4").length).toBeGreaterThan(0);

    await emit({ type: "round", round: 1, result: round });
    await emit({ type: "log", level: "info", message: "hello log" });
    expect(screen.getByText("hello log")).toBeInTheDocument();

    await emit({ type: "game_over", winner: null, scores: [5, 5] });
    expect(screen.getByText(/Shared victory/)).toBeInTheDocument();
    await emit({ type: "game_over", winner: 5, scores: [5, 5] });
    expect(screen.getByText(/Player 6 wins/)).toBeInTheDocument();
  });

  it("stops a running session", async () => {
    mocks.api.getSession.mockResolvedValue(makeDetail({ status: "running" }));
    render(<Monitor sessionId="s1" />);
    const stop = await screen.findByRole("button", { name: "Stop" });
    fireEvent.click(stop);
    expect(await screen.findByRole("button", { name: "Stopping…" })).toBeDisabled();
    await waitFor(() => expect(mocks.api.stopSession).toHaveBeenCalledWith("s1"));
  });

  it("reports stop failures and load errors", async () => {
    mocks.api.getSession.mockResolvedValue(makeDetail({ status: "running", error: "crashed" }));
    mocks.api.stopSession.mockRejectedValue(new Error("nope"));
    render(<Monitor sessionId="s1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByText(/Stop failed: nope/)).toBeInTheDocument();
    expect(screen.getByText("crashed")).toBeInTheDocument();
  });

  it("shows waiting text before any state arrives", async () => {
    mocks.api.getSession.mockResolvedValue(makeDetail({ status: "created", state: null }));
    render(<Monitor sessionId="s1" />);
    expect(await screen.findByText("Session not started yet.")).toBeInTheDocument();
  });

  it("surfaces a session load error", async () => {
    mocks.api.getSession.mockRejectedValue(new Error("gone"));
    render(<Monitor sessionId="s1" />);
    expect(await screen.findByText("gone")).toBeInTheDocument();
  });
});

describe("Replay", () => {
  it("picks the first session when none is chosen", async () => {
    const onPick = vi.fn();
    render(<Replay sessionId={null} onPick={onPick} />);
    await waitFor(() => expect(onPick).toHaveBeenCalledWith("s1"));
  });

  it("steps through moves and jumps to rounds", async () => {
    render(<Replay sessionId="s1" onPick={vi.fn()} />);
    expect(await screen.findByText(/Move 1\/3/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "▶" }));
    expect(screen.getByText(/Move 2\/3/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "◀" }));
    fireEvent.click(screen.getByRole("button", { name: "⏭" }));
    expect(screen.getByText(/Move 3\/3/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "⏮" }));
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    expect(screen.getByText(/Move 3\/3/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "1" } });
    expect(screen.getByText(/Move 2\/3/)).toBeInTheDocument();
    fireEvent.change(screen.getByTitle("Playback speed"), { target: { value: "250" } });
    fireEvent.click(screen.getByText("Ada: Red R2 +3"));
    expect(screen.getByText(/Move 1\/3/)).toBeInTheDocument();
  });

  it("plays automatically until the end", async () => {
    render(<Replay sessionId="s1" onPick={vi.fn()} />);
    await screen.findByText(/Move 1\/3/);
    fireEvent.change(screen.getByTitle("Playback speed"), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "▶ Play" }));
    await waitFor(() => expect(screen.getByText(/Move 3\/3/)).toBeInTheDocument(), { timeout: 3000 });
    await waitFor(() => expect(screen.getByRole("button", { name: "▶ Play" })).toBeInTheDocument(), { timeout: 1500 });
    fireEvent.click(screen.getByRole("button", { name: "▶ Play" }));
    fireEvent.click(screen.getByRole("button", { name: "❚❚" }));
  });

  it("handles empty histories and errors", async () => {
    mocks.api.getHistory.mockResolvedValueOnce({ ...history, moves: [] });
    const { unmount } = render(<Replay sessionId="s1" onPick={vi.fn()} />);
    expect(await screen.findByText("This session has no recorded moves.")).toBeInTheDocument();
    unmount();
    mocks.api.getHistory.mockRejectedValueOnce(new Error("bad history"));
    render(<Replay sessionId="s1" onPick={vi.fn()} />);
    expect(await screen.findByText("bad history")).toBeInTheDocument();
  });

  it("lets the user change session and reports list errors", async () => {
    const onPick = vi.fn();
    render(<Replay sessionId="s1" onPick={onPick} />);
    const select = await screen.findByRole("combobox", { name: "" });
    fireEvent.change(select, { target: { value: "s2" } });
    expect(onPick).toHaveBeenCalledWith("s2");
  });

  it("reports session list failures", async () => {
    mocks.api.listSessions.mockRejectedValue(new Error("no list"));
    render(<Replay sessionId={null} onPick={vi.fn()} />);
    expect(await screen.findByText("no list")).toBeInTheDocument();
  });
});

describe("Profiles", () => {
  it("analyses a session and shows per-player cards", async () => {
    const onPick = vi.fn();
    render(<Profiles sessionId="s1" onPick={onPick} />);
    await screen.findByText("Profile analyzer");
    fireEvent.click(screen.getByRole("button", { name: /Analy[sz]e/i }));
    expect(await screen.findByText(/20 moves analyzed/)).toBeInTheDocument();
    expect(screen.getAllByText("Score trajectory")).toHaveLength(2);
    expect(screen.getByText(/Unknown Tactician/)).toBeInTheDocument();
    expect(screen.getByText("Floor Avoidance · 3")).toBeInTheDocument();
    expect(screen.getAllByText("Archetype timeline").length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Floor Dumper", { selector: ".archetype-chip" })).length).toBeGreaterThan(0);
  });

  it("filters by selected players", async () => {
    render(<Profiles sessionId="s1" onPick={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Analy[sz]e/i }));
    await screen.findByText(/20 moves analyzed/);
    fireEvent.click(screen.getByLabelText("Bob"));
    expect(screen.getAllByText("Score trajectory")).toHaveLength(1);
    expect(screen.getAllByText("Bob").length).toBeGreaterThan(0);
  });

  it("auto-picks a session and reports analysis failures", async () => {
    const onPick = vi.fn();
    mocks.api.analyzeSession.mockRejectedValue(new Error("analysis failed"));
    render(<Profiles sessionId={null} onPick={onPick} />);
    await waitFor(() => expect(onPick).toHaveBeenCalledWith("s1"));
    const { unmount } = render(<Profiles sessionId="s1" onPick={onPick} />);
    fireEvent.click((await screen.findAllByRole("button", { name: /Analy[sz]e/i }))[1]);
    expect(await screen.findByText("analysis failed")).toBeInTheDocument();
    unmount();
  });

  it("lists archetype definitions and changes profiler", async () => {
    render(<Profiles sessionId="s1" onPick={vi.fn()} />);
    expect(await screen.findByText("Dumps tiles")).toBeInTheDocument();
    const [sessionSelect, profilerSelect] = screen.getAllByRole("combobox");
    fireEvent.change(profilerSelect, { target: { value: "basic" } });
    fireEvent.change(sessionSelect, { target: { value: "s2" } });
  });

  it("reports a failing session list", async () => {
    mocks.api.listSessions.mockRejectedValue(new Error("no sessions"));
    render(<Profiles sessionId="s1" onPick={vi.fn()} />);
    expect(await screen.findByText("no sessions")).toBeInTheDocument();
  });
});

describe("Sessions", () => {
  it("creates and starts a local session", async () => {
    const onStarted = vi.fn();
    render(<Sessions onStarted={onStarted} />);
    expect(await screen.findByText("All sessions")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("42"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Create & start session" }));
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith("new1"));
    const payload = mocks.api.createSession.mock.calls[0][0];
    expect(payload.mode).toBe("local");
    expect(payload.seed).toBe(7);
    expect(payload.players).toHaveLength(2);
    expect(mocks.api.startSession).toHaveBeenCalledWith("new1");
  });

  it("edits players: tactician, add, remove, names", async () => {
    render(<Sessions onStarted={vi.fn()} />);
    await screen.findByText("All sessions");
    fireEvent.change(screen.getByDisplayValue("Athena"), { target: { value: "Zed" } });
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[1], { target: { value: "greedy" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Add player" }));
    fireEvent.click(screen.getByRole("button", { name: "+ Add player" }));
    expect(screen.getByRole("button", { name: "+ Add player" })).toBeDisabled();
    fireEvent.click(screen.getAllByTitle("Remove player")[2]);
    expect(screen.getAllByTitle("Remove player")).toHaveLength(3);
    expect(screen.getByDisplayValue("Zed")).toBeInTheDocument();
  });

  it("configures a live session with a human seat", async () => {
    const onStarted = vi.fn();
    render(<Sessions onStarted={onStarted} />);
    await screen.findByText("All sessions");
    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "live" } });
    expect(screen.getByText("Room name")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Random" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "human" } });
    fireEvent.click(screen.getByRole("button", { name: "Create & start session" }));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    const payload = mocks.api.createSession.mock.calls[0][0];
    expect(payload.live.headless).toBe(false);
    expect(payload.players[0].tactician).toBe("human");
    // Back to local replaces the human seat.
    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "local" } });
    expect(screen.queryByText("Room name")).toBeNull();
  });

  it("clears the profiler and explainer", async () => {
    render(<Sessions onStarted={vi.fn()} />);
    await screen.findByText("All sessions");
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[selects.length - 2], { target: { value: "" } });
    fireEvent.change(selects[selects.length - 1], { target: { value: "llm" } });
    expect(screen.getByText(/falls back to the template/)).toBeInTheDocument();
    fireEvent.change(selects[selects.length - 1], { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Create & start session" }));
    await waitFor(() => expect(mocks.api.createSession).toHaveBeenCalled());
    const payload = mocks.api.createSession.mock.calls[0][0];
    expect(payload.profiler).toBeNull();
    expect(payload.explainer).toBeNull();
    expect(payload.seed).toBeNull();
  });

  it("shows creation errors", async () => {
    mocks.api.createSession.mockRejectedValue(new Error("rejected"));
    render(<Sessions onStarted={vi.fn()} />);
    await screen.findByText("All sessions");
    fireEvent.click(screen.getByRole("button", { name: "Create & start session" }));
    expect(await screen.findByText("rejected")).toBeInTheDocument();
  });

  it("falls back to built-in agents when the backend is unreachable", async () => {
    mocks.api.agents.mockRejectedValue(new Error("down"));
    render(<Sessions onStarted={vi.fn()} />);
    expect(await screen.findByText(/Backend unreachable: down/)).toBeInTheDocument();
    expect(screen.getAllByText("MCTS Profiled").length).toBeGreaterThan(0);
  });

  it("manages existing sessions", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.api.listSessions.mockResolvedValue([
      makeSession({ id: "done" }),
      makeSession({ id: "live1", status: "running" }),
      makeSession({ id: "new", status: "created" }),
    ]);
    render(<Sessions onStarted={vi.fn()} />);
    fireEvent.click((await screen.findAllByText("Delete"))[0]);
    await waitFor(() => expect(mocks.api.deleteSession).toHaveBeenCalledWith("done"));
    fireEvent.click(screen.getByText("Stop"));
    await waitFor(() => expect(mocks.api.stopSession).toHaveBeenCalledWith("live1"));
    fireEvent.click(screen.getByText("Start"));
    await waitFor(() => expect(mocks.api.startSession).toHaveBeenCalledWith("new"));
    confirm.mockReturnValue(false);
    mocks.api.deleteSession.mockClear();
    fireEvent.click(screen.getAllByText("Delete")[0]);
    expect(mocks.api.deleteSession).not.toHaveBeenCalled();
  });

  it("reports list and action failures", async () => {
    mocks.api.listSessions.mockRejectedValue(new Error("list down"));
    render(<Sessions onStarted={vi.fn()} />);
    expect(await screen.findByText("list down")).toBeInTheDocument();
    expect(screen.getByText("No sessions yet.")).toBeInTheDocument();
  });

  it("reports action failures", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.api.deleteSession.mockRejectedValue(new Error("cannot delete"));
    render(<Sessions onStarted={vi.fn()} />);
    fireEvent.click((await screen.findAllByText("Delete"))[0]);
    expect(await screen.findByText("cannot delete")).toBeInTheDocument();
  });
});
