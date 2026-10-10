import { useEffect, useState } from "react";
import { api } from "../api/client";
import { LineChart, type Annotation } from "../components/charts/LineChart";
import { ProfileCard, TraitBars } from "../components/ProfileCard";
import { StatTile } from "../components/StatTile";
import type {
  AgentInfoDTO,
  AnalysisDTO,
  ArchetypeDTO,
  PlayerAnalysisDTO,
  SessionSummaryDTO,
} from "../types";
import { COLOR_ORDER, formatNumber, formatPct } from "../types";

function SplitBar({
  parts,
  colorClass,
}: {
  parts: [string, number][];
  colorClass?: (key: string) => string;
}) {
  const total = parts.reduce((s, [, v]) => s + v, 0) || 1;
  return (
    <div className="split-bar">
      {parts.map(([key, value]) => {
        const pct = (value / total) * 100;
        if (pct <= 0) return null;
        return (
          <div
            key={key}
            className={`split-seg ${colorClass ? colorClass(key) : ""}`}
            style={{ width: `${pct}%` }}
            title={`${key}: ${Math.round(pct)}%`}
          >
            {pct >= 14 ? `${key} ${Math.round(pct)}%` : ""}
          </div>
        );
      })}
    </div>
  );
}

function PlayerAnalysisCard({ p }: { p: PlayerAnalysisDTO }) {
  const stats = p.stats;
  const timeline = p.timeline ?? [];
  const annotations: Annotation[] = [];
  // Annotate only archetype runs that persist for a few steps; momentary
  // flips early in the game would otherwise bury the chart in labels.
  timeline.forEach((t, i) => {
    if (i === 0 || t.archetype !== timeline[i - 1].archetype) {
      let run = 1;
      while (i + run < timeline.length && timeline[i + run].archetype === t.archetype) run += 1;
      if (run >= 3 || i === timeline.length - 1) {
        annotations.push({ index: i, label: t.archetype.replace(/_/g, " ") });
      }
    }
  });
  const colorParts: [string, number][] = COLOR_ORDER.map((c) => [c, stats.color_distribution?.[c] ?? 0]);
  const rowPrefs = Object.entries(stats.row_preferences ?? {}).sort(([a], [b]) => Number(a) - Number(b));
  const concepts = Object.entries(stats.concepts ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="card analysis-card">
      <div className="analysis-head">
        <h3>
          {p.player_name} <span className="muted small">· {p.tactician ?? "unknown tactician"}</span>
        </h3>
      </div>
      <div className="two-col">
        <div>
          <ProfileCard profile={p.profile} />
        </div>
        <div className="stack">
          <div className="stat-grid stat-grid-tight">
            <StatTile label="Moves" value={stats.moves} />
            <StatTile label="Final score" value={stats.final_score} />
            <StatTile label="Floor rate" value={formatPct(stats.floor_rate)} />
            <StatTile label="Completion rate" value={formatPct(stats.completion_rate)} />
            <StatTile label="Avg decision" value={`${formatNumber(stats.avg_decision_ms)} ms`} />
            <StatTile label="Avg legal moves" value={formatNumber(stats.avg_legal_actions)} />
          </div>
          <div>
            <div className="small muted">Color picks</div>
            <SplitBar parts={colorParts} colorClass={(c) => `tile-${c}`} />
          </div>
          <div>
            <div className="small muted">Source</div>
            <SplitBar parts={Object.entries(stats.source_split ?? {})} colorClass={(k) => `seg-${k}`} />
          </div>
          <div>
            <div className="small muted">Destination</div>
            <SplitBar parts={Object.entries(stats.destination_split ?? {})} colorClass={(k) => `seg-${k}`} />
          </div>
          {rowPrefs.length > 0 && (
            <div>
              <div className="small muted">Pattern rows used</div>
              <SplitBar parts={rowPrefs.map(([r, v]) => [`row ${Number(r) + 1}`, v])} colorClass={(k) => `seg-row-${k.replace("row ", "")}`} />
            </div>
          )}
          {concepts.length > 0 && (
            <div className="concept-chips">
              {concepts.map(([c, n]) => (
                <span key={c} className="concept-chip">
                  {c.replace(/_/g, " ")} · {n}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="two-col">
        <div>
          <h4>Score trajectory</h4>
          <LineChart
            labels={stats.score_trajectory.map((_, i) => String(i + 1))}
            series={[{ name: "score", values: stats.score_trajectory }]}
            xLabel="own move"
            yLabel="score"
            height={200}
            markers={false}
          />
        </div>
        <div>
          <h4>Archetype timeline</h4>
          {timeline.length === 0 ? (
            <p className="muted small">No timeline.</p>
          ) : (
            <LineChart
              labels={timeline.map((t) => String(t.step))}
              series={[{ name: "confidence", values: timeline.map((t) => t.confidence) }]}
              xLabel="step"
              yLabel="confidence"
              height={200}
              annotations={annotations}
              markers={false}
              format={(v) => `${Math.round(v * 100)}%`}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export function Profiles({
  sessionId,
  onPick,
}: {
  sessionId: string | null;
  onPick: (id: string) => void;
}) {
  const [sessions, setSessions] = useState<SessionSummaryDTO[]>([]);
  const [profilers, setProfilers] = useState<AgentInfoDTO[]>([{ name: "basic" }]);
  const [profiler, setProfiler] = useState("basic");
  const [selectedPlayers, setSelectedPlayers] = useState<Set<number>>(new Set());
  const [analysis, setAnalysis] = useState<AnalysisDTO | null>(null);
  const [archetypes, setArchetypes] = useState<ArchetypeDTO[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listSessions()
      .then((list) => {
        const sorted = [...list].sort((a, b) => {
          const ra = a.status === "completed" ? 0 : 1;
          const rb = b.status === "completed" ? 0 : 1;
          return ra - rb;
        });
        setSessions(sorted);
        if (!sessionId && sorted.length > 0) onPick(sorted[0].id);
      })
      .catch((e) => setError(e.message));
    api.agents().then((a) => setProfilers(a.profilers)).catch(() => undefined);
    api.archetypes().then(setArchetypes).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setAnalysis(null);
    setSelectedPlayers(new Set());
  }, [sessionId]);

  const session = sessions.find((s) => s.id === sessionId) ?? null;

  const analyze = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      setAnalysis(await api.analyzeSession(sessionId, profiler));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const shownPlayers =
    analysis?.players.filter((p) => selectedPlayers.size === 0 || selectedPlayers.has(p.player_index)) ?? [];

  return (
    <div className="page">
      <h2>Profile analyzer</h2>
      <p className="muted">
        Replays a recorded game through a Profiler and shows how each player's archetype,
        traits, and predicted tendencies were derived — the explainability view for opponent
        modeling.
      </p>
      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <div className="analyze-controls">
          <label className="field">
            <span>Session</span>
            <select value={sessionId ?? ""} onChange={(e) => onPick(e.target.value)}>
              <option value="" disabled>
                pick a session…
              </option>
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.id} — {s.players.map((p) => p.name).join(" vs ")} ({s.status})
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Profiler</span>
            <select value={profiler} onChange={(e) => setProfiler(e.target.value)}>
              {profilers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                  {p.description ? ` — ${p.description.length > 60 ? `${p.description.slice(0, 58)}…` : p.description}` : ""}
                </option>
              ))}
            </select>
          </label>
          {session && (
            <div className="field">
              <span>Players (none = all)</span>
              <div className="row-gap wrap">
                {session.players.map((p, i) => (
                  <label key={i} className="field-inline">
                    <input
                      type="checkbox"
                      checked={selectedPlayers.has(i)}
                      onChange={(e) => {
                        const next = new Set(selectedPlayers);
                        if (e.target.checked) next.add(i);
                        else next.delete(i);
                        setSelectedPlayers(next);
                      }}
                    />
                    <span>{p.name}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          <button className="btn-primary" onClick={analyze} disabled={!sessionId || busy}>
            {busy ? "Analyzing…" : "Analyze"}
          </button>
        </div>
      </div>

      {analysis && (
        <p className="small muted">
          {analysis.moves_analyzed} moves analyzed with the <strong>{analysis.profiler}</strong> profiler.
        </p>
      )}
      {shownPlayers.map((p) => (
        <PlayerAnalysisCard key={p.player_index} p={p} />
      ))}

      {archetypes.length > 0 && (
        <details className="card">
          <summary>
            <strong>Archetype legend</strong>
            <span className="muted small"> · {archetypes.length} archetypes and their trait signatures</span>
          </summary>
          <div className="archetype-grid">
            {archetypes.map((a) => (
              <div key={a.name} className="profile-card">
                <div className="profile-card-header">
                  <span className="archetype-chip">{a.name.replace(/_/g, " ")}</span>
                </div>
                <p className="small">{a.description}</p>
                <TraitBars traits={a.signature} />
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
