import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  CreateSessionRequest,
  PlayerSlot,
  TacticianInfoDTO,
} from "../types";

const DEFAULT_NAMES = ["Athena", "Bob", "Circe", "Dave"];

interface SlotState {
  name: string;
  tactician: string;
  simulations: number;
}

export function SessionConfig({
  onStarted,
}: {
  onStarted: (sessionId: string) => void;
}) {
  const [tacticians, setTacticians] = useState<TacticianInfoDTO[]>([]);
  const [mode, setMode] = useState<"local" | "live">("local");
  const [slots, setSlots] = useState<SlotState[]>([
    { name: DEFAULT_NAMES[0], tactician: "mcts_profiled", simulations: 300 },
    { name: DEFAULT_NAMES[1], tactician: "greedy", simulations: 300 },
  ]);
  const [profiler, setProfiler] = useState(true);
  const [explainer, setExplainer] = useState<"template" | "llm" | "">(
    "template",
  );
  const [seed, setSeed] = useState<string>("");
  const [moveDelay, setMoveDelay] = useState(300);
  const [roomName, setRoomName] = useState(
    `tiles-${Math.random().toString(36).slice(2, 7)}`,
  );
  const [headless, setHeadless] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listTacticians()
      .then(setTacticians)
      .catch((e) => setError(`Backend unreachable: ${e.message}`));
  }, []);

  const tacticianNames = tacticians.map((t) => t.name);
  const options =
    tacticianNames.length > 0
      ? tacticianNames
      : ["random", "greedy", "minimax", "mcts", "mcts_profiled"];
  const allOptions = mode === "live" ? [...options, "human"] : options;

  const setSlot = (i: number, patch: Partial<SlotState>) =>
    setSlots(slots.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const addSlot = () =>
    slots.length < 4 &&
    setSlots([
      ...slots,
      {
        name: DEFAULT_NAMES[slots.length] ?? `Player ${slots.length + 1}`,
        tactician: "greedy",
        simulations: 300,
      },
    ]);

  const removeSlot = (i: number) =>
    slots.length > 2 && setSlots(slots.filter((_, j) => j !== i));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const players: PlayerSlot[] = slots.map((s) => ({
        name: s.name,
        tactician: s.tactician,
        config: s.tactician.startsWith("mcts")
          ? { simulations: s.simulations }
          : {},
      }));
      const payload: CreateSessionRequest = {
        mode,
        players,
        profiler: profiler ? "basic" : null,
        explainer: explainer === "" ? null : explainer,
        seed: seed.trim() === "" ? null : Number(seed),
        move_delay_ms: moveDelay,
      };
      if (mode === "live") {
        payload.live = {
          room_name: roomName,
          platform_url: "https://buddyboardgames.com/azul",
          headless,
        };
      }
      const session = await api.createSession(payload);
      await api.startSession(session.id);
      onStarted(session.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="config-view">
      <h2>New session</h2>
      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <label className="field">
          <span>Mode</span>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as "local" | "live")}
          >
            <option value="local">local — simulated engine</option>
            <option value="live">live — buddyboardgames.com</option>
          </select>
        </label>
        {mode === "live" && (
          <div className="live-options">
            <label className="field">
              <span>Room name</span>
              <input
                value={roomName}
                onChange={(e) => setRoomName(e.target.value)}
              />
            </label>
            <label className="field field-inline">
              <input
                type="checkbox"
                checked={headless}
                onChange={(e) => setHeadless(e.target.checked)}
              />
              <span>headless browsers</span>
            </label>
          </div>
        )}
      </div>

      <div className="card">
        <h3>Players</h3>
        {slots.map((slot, i) => (
          <div key={i} className="slot-row">
            <input
              value={slot.name}
              onChange={(e) => setSlot(i, { name: e.target.value })}
              placeholder={`Player ${i + 1}`}
            />
            <select
              value={slot.tactician}
              onChange={(e) => setSlot(i, { tactician: e.target.value })}
            >
              {allOptions.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            {slot.tactician.startsWith("mcts") && (
              <label className="sims-field">
                sims
                <input
                  type="number"
                  min={50}
                  max={5000}
                  step={50}
                  value={slot.simulations}
                  onChange={(e) =>
                    setSlot(i, { simulations: Number(e.target.value) })
                  }
                />
              </label>
            )}
            <button
              className="btn-ghost"
              onClick={() => removeSlot(i)}
              disabled={slots.length <= 2}
              title="remove player"
            >
              ✕
            </button>
          </div>
        ))}
        <button
          className="btn-ghost"
          onClick={addSlot}
          disabled={slots.length >= 4}
        >
          + add player
        </button>
      </div>

      <div className="card">
        <h3>Agents & pacing</h3>
        <label className="field field-inline">
          <input
            type="checkbox"
            checked={profiler}
            onChange={(e) => setProfiler(e.target.checked)}
          />
          <span>Profiler (opponent modeling & archetypes)</span>
        </label>
        <label className="field">
          <span>Explainer</span>
          <select
            value={explainer}
            onChange={(e) =>
              setExplainer(e.target.value as "template" | "llm" | "")
            }
          >
            <option value="template">template (deterministic)</option>
            <option value="llm">llm (requires API key on backend)</option>
            <option value="">none</option>
          </select>
        </label>
        <label className="field">
          <span>Seed (local mode, blank = random)</span>
          <input
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="42"
          />
        </label>
        <label className="field">
          <span>Move delay: {moveDelay} ms</span>
          <input
            type="range"
            min={0}
            max={2000}
            step={100}
            value={moveDelay}
            onChange={(e) => setMoveDelay(Number(e.target.value))}
          />
        </label>
      </div>

      <button className="btn-primary" onClick={submit} disabled={busy}>
        {busy ? "Starting…" : "Create & start session"}
      </button>
    </div>
  );
}
