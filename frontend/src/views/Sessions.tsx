import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { defaultsFor, ParamForm, type ParamValues } from "../components/ParamForm";
import { SessionCard } from "../components/SessionCard";
import type {
  AgentInfoDTO,
  AgentsDTO,
  CreateSessionRequest,
  PlayerSlot,
  SessionSummaryDTO,
} from "../types";

const DEFAULT_NAMES = ["Athena", "Bob", "Circe", "Dave"];
const PLATFORM_URL = "https://buddyboardgames.com/azul";

const FALLBACK_AGENTS: AgentsDTO = {
  tacticians: ["random", "greedy", "minimax", "mcts", "mcts_profiled"].map((name) => ({ name, params: [] })),
  profilers: [{ name: "basic" }],
  explainers: [{ name: "template" }, { name: "llm", requires: "ANTHROPIC_API_KEY" }],
};

const HUMAN: AgentInfoDTO = {
  name: "human",
  description: "A person joins via the room link (live mode only).",
  params: [],
};

interface SlotState {
  name: string;
  tactician: string;
  config: ParamValues;
}

function randomRoom(): string {
  const adjectives = ["swift", "bold", "calm", "keen", "wild", "zen", "epic"];
  const nouns = ["fox", "owl", "lynx", "hawk", "raven", "elk", "tiger"];
  const pick = (xs: string[]) => xs[Math.floor(Math.random() * xs.length)];
  return `tiles-${pick(adjectives)}-${pick(nouns)}-${Math.floor(Math.random() * 100)}`;
}

export function Sessions({ onStarted }: { onStarted: (id: string) => void }) {
  const [agents, setAgents] = useState<AgentsDTO>(FALLBACK_AGENTS);
  const [mode, setMode] = useState<"local" | "live">("local");
  const [slots, setSlots] = useState<SlotState[]>([
    { name: DEFAULT_NAMES[0], tactician: "mcts_profiled", config: { simulations: 300 } },
    { name: DEFAULT_NAMES[1], tactician: "greedy", config: {} },
  ]);
  const [profiler, setProfiler] = useState<string>("basic");
  const [explainer, setExplainer] = useState<string>("template");
  const [seed, setSeed] = useState("");
  const [moveDelay, setMoveDelay] = useState(300);
  const [roomName, setRoomName] = useState(randomRoom);
  const [platformUrl, setPlatformUrl] = useState(PLATFORM_URL);
  const [headless, setHeadless] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummaryDTO[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  useEffect(() => {
    api
      .agents()
      .then((a) => {
        setAgents(a);
        // Re-seed slot configs with the real param defaults.
        setSlots((prev) =>
          prev.map((s) => {
            const info = a.tacticians.find((t) => t.name === s.tactician);
            return info ? { ...s, config: { ...defaultsFor(info.params ?? []), ...s.config } } : s;
          }),
        );
      })
      .catch((e) => setError(`Backend unreachable: ${e.message}`));
  }, []);

  const loadSessions = useCallback(() => {
    api
      .listSessions()
      .then((list) => {
        setSessions(list);
        setListError(null);
      })
      .catch((e) => setListError(e.message));
  }, []);

  useEffect(() => {
    loadSessions();
    const timer = window.setInterval(loadSessions, 3000);
    return () => window.clearInterval(timer);
  }, [loadSessions]);

  const tacticianOptions: AgentInfoDTO[] =
    mode === "live" ? [...agents.tacticians, HUMAN] : agents.tacticians;

  const infoFor = (name: string): AgentInfoDTO | undefined =>
    name === "human" ? HUMAN : agents.tacticians.find((t) => t.name === name);

  const setSlot = (i: number, patch: Partial<SlotState>) =>
    setSlots(slots.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const changeTactician = (i: number, name: string) => {
    const info = infoFor(name);
    setSlot(i, { tactician: name, config: defaultsFor(info?.params ?? []) });
  };

  const addSlot = () =>
    slots.length < 4 &&
    setSlots([
      ...slots,
      {
        name: DEFAULT_NAMES[slots.length] ?? `Player ${slots.length + 1}`,
        tactician: "greedy",
        config: defaultsFor(infoFor("greedy")?.params ?? []),
      },
    ]);

  const removeSlot = (i: number) =>
    slots.length > 2 && setSlots(slots.filter((_, j) => j !== i));

  const switchMode = (next: "local" | "live") => {
    setMode(next);
    if (next === "local") {
      setSlots(slots.map((s) => (s.tactician === "human" ? { ...s, tactician: "greedy", config: {} } : s)));
    }
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const players: PlayerSlot[] = slots.map((s) => ({
        name: s.name.trim() || "Player",
        tactician: s.tactician,
        config: Object.fromEntries(
          Object.entries(s.config).filter(([, v]) => v !== null && v !== ""),
        ),
      }));
      const payload: CreateSessionRequest = {
        mode,
        players,
        profiler: profiler === "" ? null : profiler,
        explainer: explainer === "" ? null : explainer,
        seed: seed.trim() === "" ? null : Number(seed),
        move_delay_ms: moveDelay,
      };
      if (mode === "live") {
        payload.live = { room_name: roomName.trim(), platform_url: platformUrl, headless };
        // The platform refuses a name while an earlier game under it is still
        // alive, so never offer the same name twice.
        setRoomName(randomRoom());
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

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      loadSessions();
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    }
  };

  const explainerInfo = agents.explainers.find((e) => e.name === explainer);

  return (
    <div className="page">
      <h2>Sessions</h2>
      {error && <div className="error-banner">{error}</div>}

      <div className="two-col two-col-wide">
        <div className="config-view">
          <div className="card">
            <h3>New session</h3>
            <label className="field">
              <span>Mode</span>
              <select value={mode} onChange={(e) => switchMode(e.target.value as "local" | "live")}>
                <option value="local">local — simulated engine</option>
                <option value="live">live — buddyboardgames.com (Playwright)</option>
              </select>
            </label>
            {mode === "live" && (
              <div className="live-options">
                <label className="field">
                  <span>Room name</span>
                  <div className="row-gap">
                    <input value={roomName} onChange={(e) => setRoomName(e.target.value)} maxLength={20} />
                    <button className="btn-ghost" onClick={() => setRoomName(randomRoom())} type="button">
                      random
                    </button>
                  </div>
                </label>
                <label className="field">
                  <span>Platform URL</span>
                  <input value={platformUrl} onChange={(e) => setPlatformUrl(e.target.value)} />
                </label>
                <label className="field field-inline">
                  <input type="checkbox" checked={headless} onChange={(e) => setHeadless(e.target.checked)} />
                  <span>headless browsers (untick to watch each bot's Chromium window)</span>
                </label>
                <p className="small muted">
                  Each bot seat gets its own Chromium browser in the room. Add a{" "}
                  <strong>human</strong> seat to play against the agents yourself via the join link
                  shown in the Monitor.
                </p>
              </div>
            )}
          </div>

          <div className="card">
            <h3>Players</h3>
            {slots.map((slot, i) => {
              const info = infoFor(slot.tactician);
              return (
                <div key={i} className="slot-block">
                  <div className="slot-row">
                    <span className="slot-index muted small">{i + 1}</span>
                    <input
                      value={slot.name}
                      onChange={(e) => setSlot(i, { name: e.target.value })}
                      placeholder={`Player ${i + 1}`}
                      maxLength={16}
                    />
                    <select value={slot.tactician} onChange={(e) => changeTactician(i, e.target.value)}>
                      {tacticianOptions.map((t) => (
                        <option key={t.name} value={t.name}>
                          {t.name}
                          {t.uses_opponent_model ? " (opponent-aware)" : ""}
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn-ghost"
                      onClick={() => removeSlot(i)}
                      disabled={slots.length <= 2}
                      title="remove player"
                      type="button"
                    >
                      ✕
                    </button>
                  </div>
                  {info?.description && <div className="small muted slot-desc">{info.description}</div>}
                  <ParamForm
                    compact
                    params={info?.params ?? []}
                    values={slot.config}
                    onChange={(name, value) => setSlot(i, { config: { ...slot.config, [name]: value } })}
                  />
                </div>
              );
            })}
            <button className="btn-ghost" onClick={addSlot} disabled={slots.length >= 4} type="button">
              + add player
            </button>
          </div>

          <div className="card">
            <h3>Agents &amp; pacing</h3>
            <label className="field">
              <span>Profiler (opponent modeling &amp; archetypes)</span>
              <select value={profiler} onChange={(e) => setProfiler(e.target.value)}>
                {agents.profilers.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                    {p.description ? ` — ${p.description.length > 72 ? `${p.description.slice(0, 70)}…` : p.description}` : ""}
                  </option>
                ))}
                <option value="">none</option>
              </select>
            </label>
            <label className="field">
              <span>Explainer</span>
              <select value={explainer} onChange={(e) => setExplainer(e.target.value)}>
                {agents.explainers.map((x) => (
                  <option key={x.name} value={x.name}>
                    {x.name}
                    {x.requires ? ` (requires ${x.requires})` : ""}
                  </option>
                ))}
                <option value="">none</option>
              </select>
              {explainerInfo?.requires && (
                <span className="small muted">
                  Needs <code>{explainerInfo.requires}</code> on the backend; falls back to the template
                  explainer otherwise.
                </span>
              )}
            </label>
            <label className="field">
              <span>Seed (local mode, blank = random)</span>
              <input value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="42" />
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

          <button className="btn-primary" onClick={submit} disabled={busy} type="button">
            {busy ? "Starting…" : "Create & start session"}
          </button>
        </div>

        <div className="card">
          <h3>All sessions</h3>
          {listError && <div className="error-banner">{listError}</div>}
          {sessions.length === 0 ? (
            <p className="muted">No sessions yet.</p>
          ) : (
            <div className="session-list">
              {sessions.map((s) => (
                <SessionCard
                  key={s.id}
                  session={s}
                  onStart={(id) => act(() => api.startSession(id))}
                  onStop={(id) => act(() => api.stopSession(id))}
                  onDelete={(id) => {
                    if (window.confirm(`Delete session ${id} and its recorded moves?`)) {
                      act(() => api.deleteSession(id));
                    }
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
