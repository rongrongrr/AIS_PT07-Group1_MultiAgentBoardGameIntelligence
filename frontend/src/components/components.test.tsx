import { fireEvent, render, screen } from "@testing-library/react";
import { Board } from "./Board";
import { MoveLog } from "./MoveLog";
import { defaultsFor, ParamForm } from "./ParamForm";
import { ProfileCard, TraitBars } from "./ProfileCard";
import { RoundTable } from "./RoundTable";
import { isRunning, SessionCard } from "./SessionCard";
import { StatTile } from "./StatTile";
import { StatusBadge } from "./StatusBadge";
import { SystemLog } from "./SystemLog";
import { Slot, Tile } from "./Tile";
import { XaiPanel } from "./XaiPanel";
import { makeRecord, makeSession, makeState, profile, round } from "../test/fixtures";

describe("Tile and Slot", () => {
  it("labels tiles with proper case", () => {
    render(<Tile tile="blue" />);
    expect(screen.getByTitle("Blue")).toBeInTheDocument();
  });
  it("renders the first player token", () => {
    render(<Tile tile="firstPlayer" />);
    expect(screen.getByTitle("First Player Token")).toHaveTextContent("1");
  });
  it("renders dimmed, filled and empty slots", () => {
    const { container, rerender } = render(<Slot color="red" />);
    expect(container.querySelector(".tile-dim")).not.toBeNull();
    rerender(<Slot color="red" filled />);
    expect(container.querySelector(".tile-dim")).toBeNull();
    rerender(<Slot />);
    expect(container.querySelector(".tile-empty")).not.toBeNull();
  });
});

describe("StatTile and StatusBadge", () => {
  it("shows label, value and hint", () => {
    render(<StatTile label="Moves" value={5} hint="total" />);
    expect(screen.getByText("Moves")).toBeInTheDocument();
    expect(screen.getByText("total")).toBeInTheDocument();
  });
  it("omits the hint when absent", () => {
    const { container } = render(<StatTile label="Moves" value="5" />);
    expect(container.querySelector(".stat-hint")).toBeNull();
  });
  it("title-cases the status", () => {
    render(<StatusBadge status="game_over" />);
    expect(screen.getByText("Game Over")).toBeInTheDocument();
  });
});

describe("Board", () => {
  it("renders factories, centre, scores and overflow", () => {
    render(<Board state={makeState()} />);
    expect(screen.getByText("Round 2")).toBeInTheDocument();
    expect(screen.getByText("Drafting")).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Player 2")).toBeInTheDocument();
    expect(screen.getByText("F1")).toBeInTheDocument();
    expect(screen.getByText("Center")).toBeInTheDocument();
    expect(screen.getByText("+1 Overflow")).toBeInTheDocument();
    expect(screen.getByTitle("Holds First Player Token")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
  it("shows an empty centre pool", () => {
    render(<Board state={makeState({ center_pool: [], phase: "game_over" })} />);
    expect(screen.getAllByText("Empty").length).toBeGreaterThan(0);
    expect(screen.getByText("Game Over")).toBeInTheDocument();
  });
});

describe("ProfileCard", () => {
  it("shows archetype, confidence and traits without tempo", () => {
    render(<ProfileCard profile={profile} />);
    expect(screen.getByText("Floor Dumper")).toBeInTheDocument();
    expect(screen.getByText(/Confidence 72%/)).toBeInTheDocument();
    expect(screen.getByText("Aggression")).toBeInTheDocument();
    expect(screen.queryByText("Tempo Ms")).toBeNull();
    expect(screen.getByText("Likes the floor.")).toBeInTheDocument();
  });
  it("hides traits when compact", () => {
    render(<ProfileCard profile={{ ...profile, summary: "" }} compact />);
    expect(screen.queryByText("Aggression")).toBeNull();
  });
  it("renders nothing for empty traits", () => {
    const { container } = render(<TraitBars traits={{ tempo_ms: 3 }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("RoundTable", () => {
  it("shows an empty message", () => {
    render(<RoundTable rounds={[]} players={[]} />);
    expect(screen.getByText("No rounds resolved yet.")).toBeInTheDocument();
  });
  it("summarises tilings and jumps to rounds", () => {
    const onJump = vi.fn();
    render(<RoundTable rounds={[round, { ...round, round: 2, tilings: [], game_over: false, scores: undefined as never, floor_penalties: undefined as never }]} players={["Ada", "Bob"]} onJump={onJump} />);
    expect(screen.getByText("Ada: Red R2 +3")).toBeInTheDocument();
    expect(screen.getByText("· Final")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Ada: Red R2 +3"));
    expect(onJump).toHaveBeenCalledWith(1);
  });
  it("works without a jump handler", () => {
    render(<RoundTable rounds={[round]} players={["Ada"]} />);
    fireEvent.click(screen.getByText("Ada: Red R2 +3"));
  });
});

describe("SessionCard", () => {
  it("recognises running states", () => {
    expect(isRunning("running")).toBe(true);
    expect(isRunning("completed")).toBe(false);
  });
  it("offers delete for finished sessions", () => {
    const onDelete = vi.fn();
    render(<SessionCard session={makeSession()} onDelete={onDelete} />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Local")).toBeInTheDocument();
    expect(screen.getByText("Ada (greedy) vs Bob (mcts)")).toBeInTheDocument();
    expect(screen.getByText(/12 Moves/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Delete"));
    expect(onDelete).toHaveBeenCalledWith("s1");
    expect(screen.queryByText("Stop")).toBeNull();
  });
  it("offers stop while running", () => {
    const onStop = vi.fn();
    render(<SessionCard session={makeSession({ status: "running" })} onStop={onStop} />);
    fireEvent.click(screen.getByText("Stop"));
    expect(onStop).toHaveBeenCalledWith("s1");
    expect(screen.queryByText("Delete")).toBeNull();
  });
  it("offers start for created sessions", () => {
    const onStart = vi.fn();
    render(
      <SessionCard
        session={makeSession({ status: "created", steps: null, scores: null, winner_name: null })}
        onStart={onStart}
      />,
    );
    fireEvent.click(screen.getByText("Start"));
    expect(onStart).toHaveBeenCalledWith("s1");
  });
  it("links to monitor and replay", () => {
    render(<SessionCard session={makeSession()} />);
    expect(screen.getByText("Monitor")).toHaveAttribute("href", "#/monitor/s1");
    expect(screen.getByText("Replay")).toHaveAttribute("href", "#/replay/s1");
  });
});

describe("SystemLog", () => {
  const entries = [
    { ts: "1", level: "info", message: "hello", player: "Ada", phase: "drafting" },
    { ts: "2", level: "error", message: "boom" },
  ];
  it("shows an empty message", () => {
    render(<SystemLog entries={[]} />);
    expect(screen.getByText("No log entries.")).toBeInTheDocument();
  });
  it("filters by level", () => {
    render(<SystemLog entries={entries} />);
    expect(screen.getByText("hello")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "error" } });
    expect(screen.queryByText("hello")).toBeNull();
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Warning" })).toBeInTheDocument();
  });
});

describe("MoveLog", () => {
  it("shows an empty message", () => {
    render(<MoveLog moves={[]} />);
    expect(screen.getByText("No moves recorded yet.")).toBeInTheDocument();
  });
  it("groups by round, selects and expands moves", () => {
    const onSelect = vi.fn();
    const moves = [
      makeRecord({ step: 2, round: 1 }),
      makeRecord({ step: 1, round: 1, timing: null, state_after: null, explanation: null }),
      makeRecord({
        step: 3,
        round: 2,
        validation: { ok: false, violation: { predicate: "p", message: "illegal" }, attempts: 3 },
        timing: { decide_ms: 1, total_ms: 2 },
      }),
    ];
    render(<MoveLog moves={moves} selectedStep={3} onSelect={onSelect} />);
    expect(screen.getByText(/Round 2/)).toBeInTheDocument();
    expect(screen.getByText(/Round 1/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Red: Factory 3 → Row 4")[0]);
    expect(onSelect).toHaveBeenCalled();
    expect(screen.getByText(/Rejected: illegal/)).toBeInTheDocument();
    expect(screen.getByText(/Attempts 3/)).toBeInTheDocument();
  });
  it("shows explanation text and execute timing when expanded", () => {
    render(<MoveLog moves={[makeRecord()]} />);
    fireEvent.click(screen.getByText("Red: Factory 3 → Row 4"));
    expect(screen.getByText("Takes red.")).toBeInTheDocument();
    expect(screen.getByText(/Execute 100 ms/)).toBeInTheDocument();
  });
});

describe("XaiPanel", () => {
  it("prompts before the first move", () => {
    render(<XaiPanel record={null} />);
    expect(screen.getByText(/No moves yet/)).toBeInTheDocument();
  });
  it("explains a full decision", () => {
    render(<XaiPanel record={makeRecord()} />);
    expect(screen.getByText("Why this move")).toBeInTheDocument();
    expect(screen.getByText("Takes red.")).toBeInTheDocument();
    expect(screen.getByText("Floor Avoidance")).toBeInTheDocument();
    expect(screen.getByText("Opponent-Aware")).toBeInTheDocument();
    expect(screen.getByText(/200 Sims/)).toBeInTheDocument();
    expect(screen.getByText("Expected line")).toBeInTheDocument();
    expect(screen.getByText(/Validator OK After 2 attempts/)).toBeInTheDocument();
    expect(screen.getByText("Floor Dumper")).toBeInTheDocument();
  });
  it("copes with missing report, explanation and profiles", () => {
    render(
      <XaiPanel
        record={makeRecord({
          report: null,
          explanation: null,
          profiles: null,
          timing: null,
          validation: { ok: false, violation: null },
        })}
      />,
    );
    expect(screen.getByText("No explanation attached to this move.")).toBeInTheDocument();
    expect(screen.getByText(/Validator Rejected/)).toBeInTheDocument();
  });
});

describe("ParamForm", () => {
  const params = [
    { name: "flag", type: "bool", default: true },
    { name: "mode_choice", type: "choice", choices: ["a", "b"] },
    { name: "count", type: "int", min: 1, max: 9, description: "How many" },
    { name: "ratio", type: "float", step: 0.1 },
    { name: "label", type: "str" },
  ];

  it("builds defaults from specs", () => {
    expect(defaultsFor(params)).toEqual({
      flag: true,
      mode_choice: "a",
      count: 0,
      ratio: 0,
      label: "",
    });
    expect(defaultsFor([{ name: "b", type: "bool" }, { name: "c", type: "choice" }])).toEqual({ b: false, c: "" });
  });

  it("renders nothing without params", () => {
    const { container } = render(<ParamForm params={[]} values={{}} onChange={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("emits typed changes", () => {
    const onChange = vi.fn();
    render(<ParamForm params={params} values={defaultsFor(params)} onChange={onChange} />);
    expect(screen.getByText("Mode Choice")).toBeInTheDocument();
    expect(screen.getByText("How many")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Flag"));
    expect(onChange).toHaveBeenLastCalledWith("flag", false);
    fireEvent.change(screen.getByLabelText(/Mode Choice/), { target: { value: "b" } });
    expect(onChange).toHaveBeenLastCalledWith("mode_choice", "b");
    fireEvent.change(screen.getByLabelText(/Count/), { target: { value: "5" } });
    expect(onChange).toHaveBeenLastCalledWith("count", 5);
    fireEvent.change(screen.getByLabelText(/Ratio/), { target: { value: "0.5" } });
    expect(onChange).toHaveBeenLastCalledWith("ratio", 0.5);
    fireEvent.change(screen.getByLabelText(/Count/), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith("count", null);
    fireEvent.change(screen.getByLabelText(/Label/), { target: { value: "hi" } });
    expect(onChange).toHaveBeenLastCalledWith("label", "hi");
  });

  it("hides descriptions when compact", () => {
    render(<ParamForm compact params={params} values={{}} onChange={() => undefined} />);
    expect(screen.queryByText("How many")).toBeNull();
  });
});

describe("ParamForm with several forms on one page", () => {
  it("gives each form its own element ids so labels act on their own input", () => {
    const params = [{ name: "table_aware", type: "bool", default: false }];
    const first = vi.fn();
    const second = vi.fn();
    render(
      <>
        <ParamForm compact params={params} values={{ table_aware: false }} onChange={first} />
        <ParamForm compact params={params} values={{ table_aware: false }} onChange={second} />
      </>,
    );
    const labels = screen.getAllByText("Table Aware");
    fireEvent.click(labels[1]);
    expect(second).toHaveBeenCalledWith("table_aware", true);
    expect(first).not.toHaveBeenCalled();
  });
});
