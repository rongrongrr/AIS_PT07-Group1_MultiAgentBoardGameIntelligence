import { titleCase } from "../format";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { BarChart } from "../components/charts/BarChart";
import { SessionCard } from "../components/SessionCard";
import { StatTile } from "../components/StatTile";
import { hrefFor } from "../router";
import type { StatsDTO } from "../types";
import { formatNumber } from "../types";

const LATENCY_KEYS = ["decide_ms", "validate_ms", "explain_ms", "total_ms"];

export function Dashboard() {
  const [stats, setStats] = useState<StatsDTO | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .stats()
        .then((s) => {
          if (!cancelled) {
            setStats(s);
            setError(null);
          }
        })
        .catch((e) => !cancelled && setError(e.message));
    load();
    const timer = window.setInterval(load, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (error && !stats) {
    return (
      <div className="page">
        <h2>Dashboard</h2>
        <div className="error-banner">Backend unreachable: {error}</div>
      </div>
    );
  }
  if (!stats) {
    return (
      <div className="page">
        <h2>Dashboard</h2>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  const byStatus = stats.sessions.by_status ?? {};
  const tacticians = [...(stats.tacticians ?? [])].sort(
    (a, b) => b.win_rate - a.win_rate,
  );
  const archetypes = Object.entries(stats.archetypes ?? {}).sort(
    (a, b) => b[1] - a[1],
  );
  const empty = stats.sessions.total === 0;

  return (
    <div className="page">
      <div className="page-header">
        <h2>Dashboard</h2>
        <a className="btn-primary" href={hrefFor("sessions")}>
          New session
        </a>
      </div>

      <div className="stat-grid">
        <StatTile label="Sessions" value={stats.sessions.total} hint={`${byStatus.completed ?? 0} completed`} />
        <StatTile label="Running now" value={byStatus.running ?? 0} hint={`${stats.sessions.by_mode?.live ?? 0} live`} />
        <StatTile label="Moves recorded" value={stats.moves_total.toLocaleString()} hint="immutable ledger" />
        <StatTile label="Experiments" value={stats.experiments.total} hint={`${stats.experiments.by_status?.completed ?? 0} completed`} />
      </div>

      {empty ? (
        <div className="card empty-state">
          <p>
            No games recorded yet. Start a local session to watch the Decision
            Stack play, or run an experiment to populate the ledger.
          </p>
          <div className="row-gap">
            <a className="btn-primary" href={hrefFor("sessions")}>
              Create a session
            </a>
            <a className="btn-ghost" href={hrefFor("experiments")}>
              Run an experiment
            </a>
          </div>
        </div>
      ) : (
        <div className="two-col">
          <div className="card">
            <h3>Win rate by tactician</h3>
            {tacticians.length === 0 ? (
              <p className="muted small">No finished games yet.</p>
            ) : (
              <>
                <BarChart
                  labels={tacticians.map((t) => titleCase(t.name))}
                  series={[{ name: "Win Rate", values: tacticians.map((t) => t.win_rate) }]}
                  yLabel="Win Rate"
                  format={(v) => `${Math.round(v * 100)}%`}
                />
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Tactician</th>
                      <th>Games</th>
                      <th>Wins</th>
                      <th>Avg Score</th>
                      <th>Avg Decide</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tacticians.map((t) => (
                      <tr key={t.name}>
                        <td>{titleCase(t.name)}</td>
                        <td className="num">{t.games}</td>
                        <td className="num">{t.wins}</td>
                        <td className="num">{formatNumber(t.avg_score)}</td>
                        <td className="num">{formatNumber(t.avg_decide_ms)} ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="stack">
            <div className="card">
              <h3>Pipeline latency</h3>
              <div className="stat-grid stat-grid-tight">
                {LATENCY_KEYS.map((key) => {
                  const l = stats.latency?.[key];
                  return (
                    <StatTile
                      key={key}
                      label={titleCase(key.replace("_ms", ""))}
                      value={l?.p50 != null ? `${formatNumber(l.p50)} ms` : "—"}
                      hint={l ? `P90 ${formatNumber(l.p90)} · Max ${formatNumber(l.max)} ms` : "No data"}
                    />
                  );
                })}
              </div>
            </div>
            <div className="card">
              <h3>Archetypes observed</h3>
              {archetypes.length === 0 ? (
                <p className="muted small">Run a session with the Profiler enabled.</p>
              ) : (
                <BarChart
                  labels={archetypes.map(([n]) => titleCase(n))}
                  series={[{ name: "Players", values: archetypes.map(([, v]) => v) }]}
                  yLabel="Players"
                  height={200}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {stats.recent_sessions.length > 0 && (
        <div className="card">
          <h3>Recent sessions</h3>
          <div className="session-list">
            {stats.recent_sessions.map((s) => (
              <SessionCard key={s.id} session={s} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
