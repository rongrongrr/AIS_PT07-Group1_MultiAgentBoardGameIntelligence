import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Experiments } from "./Experiments";
import type { ExperimentWsEvent } from "../types";
import { makeRun } from "../test/fixtures";

const mocks = vi.hoisted(() => ({
  api: {
    experimentTypes: vi.fn(),
    listExperiments: vi.fn(),
    getExperiment: vi.fn(),
    startExperiment: vi.fn(),
    stopExperiment: vi.fn(),
    deleteExperiment: vi.fn(),
  },
  ws: { handler: null as ((e: ExperimentWsEvent) => void) | null },
  downloadJson: vi.fn(),
}));

vi.mock("../api/client", () => ({
  api: mocks.api,
  connectExperimentWs: vi.fn((_id: string, onEvent: (e: ExperimentWsEvent) => void) => {
    mocks.ws.handler = onEvent;
    return { close: vi.fn() };
  }),
  downloadJson: mocks.downloadJson,
}));

const types = [
  {
    name: "tournament",
    title: "Tournament",
    description: "Round robin.",
    report_section: "§5.1",
    estimated: "2 min",
    params: [{ name: "games", type: "int", default: 4 }],
  },
  { name: "latency_profile", title: "Latency", params: [] },
];

const emit = (e: ExperimentWsEvent) => act(() => mocks.ws.handler?.(e));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.api.experimentTypes.mockResolvedValue(types);
  mocks.api.listExperiments.mockResolvedValue([
    makeRun(),
    makeRun({ id: "e2", title: "", status: "running", progress: { done: 1, total: 4 } }),
    makeRun({ id: "e3", status: "created", progress: null }),
  ]);
  mocks.api.getExperiment.mockResolvedValue(makeRun());
  mocks.api.startExperiment.mockResolvedValue(makeRun({ id: "new" }));
  mocks.api.stopExperiment.mockResolvedValue({ status: "stopped" });
  mocks.api.deleteExperiment.mockResolvedValue({ deleted: "e1" });
});

describe("Experiments launcher", () => {
  it("lists types and runs with proper casing", async () => {
    render(<Experiments runId={null} onPick={vi.fn()} />);
    expect(await screen.findByText("Round robin.")).toBeInTheDocument();
    expect(screen.getByText("Estimated: 2 min")).toBeInTheDocument();
    expect(screen.getByText("Select a run to see its progress and results, or launch a new one.")).toBeInTheDocument();
    expect((await screen.findAllByText("Tournament")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Running").length).toBeGreaterThan(0);
  });

  it("starts a run and navigates to it", async () => {
    const onPick = vi.fn();
    render(<Experiments runId={null} onPick={onPick} />);
    await screen.findByText("Round robin.");
    fireEvent.change(screen.getByLabelText(/Games/), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Tournament" }));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith("new"));
    expect(mocks.api.startExperiment).toHaveBeenCalledWith("tournament", { games: 8 });
  });

  it("switches type and reports start failures", async () => {
    mocks.api.startExperiment.mockRejectedValue(new Error("cannot start"));
    render(<Experiments runId={null} onPick={vi.fn()} />);
    await screen.findByText("Round robin.");
    fireEvent.click(screen.getByRole("button", { name: "Latency" }));
    fireEvent.click(screen.getByRole("button", { name: "Run Latency" }));
    expect(await screen.findByText("cannot start")).toBeInTheDocument();
  });

  it("handles no types and backend errors", async () => {
    mocks.api.experimentTypes.mockResolvedValueOnce([]);
    const { unmount } = render(<Experiments runId={null} onPick={vi.fn()} />);
    expect(await screen.findByText("No experiment types available.")).toBeInTheDocument();
    unmount();
    mocks.api.experimentTypes.mockRejectedValueOnce(new Error("down"));
    mocks.api.listExperiments.mockResolvedValueOnce([]);
    render(<Experiments runId={null} onPick={vi.fn()} />);
    expect(await screen.findByText(/Backend unreachable: down/)).toBeInTheDocument();
    expect(await screen.findByText("No runs yet.")).toBeInTheDocument();
  });

  it("picks a run from the list", async () => {
    const onPick = vi.fn();
    render(<Experiments runId="e1" onPick={onPick} />);
    const items = await screen.findAllByText(/Created|Jan/);
    expect(items.length).toBeGreaterThan(0);
    fireEvent.click(document.querySelectorAll(".run-item")[1]);
    expect(onPick).toHaveBeenCalledWith("e2");
  });
});

describe("Experiment run detail", () => {
  it("renders results: metrics, tables, charts and raw JSON", async () => {
    render(<Experiments runId="e1" onPick={vi.fn()} />);
    expect(await screen.findByText("Mcts wins.")).toBeInTheDocument();
    expect(screen.getByText("Win Rate")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
    expect(screen.getByText("Raw result JSON")).toBeInTheDocument();
    expect(screen.getByText(/Games=4/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));
    expect(mocks.downloadJson).toHaveBeenCalledWith("e1.json", expect.objectContaining({ id: "e1" }));
  });

  it("deletes a finished run after confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const detailDelete = async () => {
      const buttons = await screen.findAllByRole("button", { name: "Delete" });
      fireEvent.click(buttons[0]);
    };
    render(<Experiments runId="e1" onPick={vi.fn()} />);
    await detailDelete();
    await waitFor(() => expect(mocks.api.deleteExperiment).toHaveBeenCalledWith("e1"));
    confirm.mockReturnValue(false);
    mocks.api.deleteExperiment.mockClear();
    await detailDelete();
    expect(mocks.api.deleteExperiment).not.toHaveBeenCalled();
  });

  it("shows delete failures", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.api.deleteExperiment.mockRejectedValue(new Error("locked"));
    render(<Experiments runId="e1" onPick={vi.fn()} />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Delete" }))[0]);
    expect(await screen.findByText("locked")).toBeInTheDocument();
  });

  it("follows a running experiment over the socket", async () => {
    mocks.api.getExperiment.mockResolvedValue(
      makeRun({ status: "running", result: null, progress: { done: 1, total: 4, message: "warming" } }),
    );
    render(<Experiments runId="e1" onPick={vi.fn()} />);
    expect(await screen.findByText(/warming/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(mocks.api.stopExperiment).toHaveBeenCalledWith("e1");

    await emit({ type: "progress", done: 2, total: 4, message: "half" });
    expect(screen.getByText(/half/)).toBeInTheDocument();
    await emit({ type: "log", level: "info", message: "log line" });
    expect(screen.getByText(/Log · 1/)).toBeInTheDocument();
    await emit({ type: "status", status: "running" });
    await emit({ type: "result", result: makeRun().result! });
    expect(await screen.findByText("Mcts wins.")).toBeInTheDocument();
    mocks.api.getExperiment.mockResolvedValue(makeRun());
    await emit({ type: "status", status: "completed" });
  });

  it("shows empty and failed states", async () => {
    mocks.api.getExperiment.mockResolvedValueOnce(makeRun({ result: null, error: "it broke", progress: null }));
    const { unmount } = render(<Experiments runId="e1" onPick={vi.fn()} />);
    expect(await screen.findByText("it broke")).toBeInTheDocument();
    expect(screen.getByText("No result.")).toBeInTheDocument();
    unmount();
    mocks.api.getExperiment.mockRejectedValueOnce(new Error("missing"));
    render(<Experiments runId="e9" onPick={vi.fn()} />);
    expect(await screen.findByText("missing")).toBeInTheDocument();
  });

  it("renders results without optional parts", async () => {
    mocks.api.getExperiment.mockResolvedValue(
      makeRun({ result: { summary: "", metrics: {}, tables: [], series: [] } }),
    );
    render(<Experiments runId="e1" onPick={vi.fn()} />);
    await screen.findByText("Download JSON");
    expect(screen.queryByText("Raw result JSON")).toBeNull();
  });
});
