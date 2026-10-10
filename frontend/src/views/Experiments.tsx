import { titleCase } from "../format";
import { useCallback, useEffect, useState } from "react";
import { api, connectExperimentWs, downloadJson } from "../api/client";
import { SeriesChart } from "../components/charts/SeriesChart";
import { defaultsFor, ParamForm, type ParamValues } from "../components/ParamForm";
import { StatTile } from "../components/StatTile";
import { StatusBadge } from "../components/StatusBadge";
import type {
  CellValue,
  ExperimentResultDTO,
  ExperimentRunDTO,
  ExperimentTypeDTO,
  ExperimentWsEvent,
  LogEntry,
} from "../types";
import { formatNumber, formatTime } from "../types";

const ACTIVE = new Set(["created", "running"]);

function cell(v: CellValue): string {
  if (v == null) return "—";
  if (typeof v === "number") return formatNumber(v, 3);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return v;
}

function ResultView({ result }: { result: ExperimentResultDTO }) {
  const metrics = Object.entries(result.metrics ?? {});
  return (
    <div className="stack">
      {result.summary && <div className="summary-callout">{result.summary}</div>}
      {metrics.length > 0 && (
        <div className="stat-grid stat-grid-tight">
          {metrics.map(([k, v]) => (
            <StatTile key={k} label={titleCase(k)} value={formatNumber(v, 3)} />
          ))}
        </div>
      )}
      {(result.series ?? []).map((s, i) => (
        <SeriesChart key={`${s.title}-${i}`} series={s} />
      ))}
      {(result.tables ?? []).map((t, i) => (
        <div key={`${t.title}-${i}`} className="chart-card">
          <h4>{t.title}</h4>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  {t.columns.map((c) => (
                    <th key={c}>{titleCase(c)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {t.rows.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((v, ci) => (
                      <td key={ci} className={typeof v === "number" ? "num" : undefined}>
                        {cell(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      {result.raw !== undefined && (
        <details>
          <summary className="small muted">Raw result JSON</summary>
          <pre className="json-block">{JSON.stringify(result.raw, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

function RunDetail({ runId, onChanged }: { runId: string; onChanged: () => void }) {
  const [run, setRun] = useState<ExperimentRunDTO | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.getExperiment(runId).then(setRun).catch((e) => setError(e.message));
  }, [runId]);

  useEffect(() => {
    setRun(null);
    setLogs([]);
    setError(null);
    refresh();
    const ws = connectExperimentWs(runId, (event: ExperimentWsEvent) => {
      switch (event.type) {
        case "status":
          setRun((r) => (r ? { ...r, status: event.status } : r));
          if (!ACTIVE.has(event.status)) {
            refresh();
            onChanged();
          }
          break;
        case "progress":
          setRun((r) =>
            r ? { ...r, progress: { done: event.done, total: event.total, message: event.message } } : r,
          );
          break;
        case "log":
          setLogs((l) => [
            ...l.slice(-199),
            { ts: new Date().toLocaleTimeString(), level: event.level, message: event.message },
          ]);
          break;
        case "result":
          setRun((r) => (r ? { ...r, result: event.result, status: "completed" } : r));
          onChanged();
          break;
      }
    });
    return () => ws.close();
  }, [runId, refresh, onChanged]);

  // Poll while active in case the socket is unavailable.
  useEffect(() => {
    if (!run || !ACTIVE.has(run.status)) return;
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [run, refresh]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!run) return <p className="muted">Loading run…</p>;

  const progress = run.progress ?? { done: 0, total: 0, message: "" };
  const pct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;
  const active = ACTIVE.has(run.status);

  return (
    <div className="card">
      <div className="monitor-header">
        <h3 className="no-margin">{run.title}</h3>
        <StatusBadge status={run.status} />
        <span className="mono small">{run.id}</span>
        <span className="spacer" />
        {active && (
          <button className="btn-ghost" onClick={() => api.stopExperiment(run.id).catch(() => undefined)}>
            Stop
          </button>
        )}
        {!active && (
          <button
            className="btn-ghost btn-danger"
            onClick={() => {
              if (window.confirm(`Delete experiment ${run.id}?`)) {
                api.deleteExperiment(run.id).then(onChanged).catch((e) => setError(e.message));
              }
            }}
          >
            Delete
          </button>
        )}
        <button className="btn-ghost" onClick={() => downloadJson(`${run.id}.json`, run)}>
          Download JSON
        </button>
      </div>
      <div className="small muted">
        Params:{" "}
        {Object.entries(run.params).map(([k, v]) => (
          <span key={k} className="action-chip">
            {titleCase(k)}={String(v)}
          </span>
        ))}{" "}
        · Created {formatTime(run.created_at)}
        {run.completed_at && ` · Finished ${formatTime(run.completed_at)}`}
      </div>
      {(active || progress.total > 0) && (
        <div className="progress">
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="small muted">
            {progress.done}/{progress.total} {progress.message ? `· ${progress.message}` : ""}
          </span>
        </div>
      )}
      {run.error && <div className="error-banner">{run.error}</div>}
      {logs.length > 0 && (
        <details open={active}>
          <summary className="small muted">Log · {logs.length}</summary>
          <pre className="system-log">
            {logs.map((l) => `${l.ts} [${titleCase(l.level)}] ${l.message}`).join("\n")}
          </pre>
        </details>
      )}
      {run.result ? <ResultView result={run.result} /> : !active && <p className="muted small">No result.</p>}
    </div>
  );
}

export function Experiments({
  runId,
  onPick,
}: {
  runId: string | null;
  onPick: (id: string | null) => void;
}) {
  const [types, setTypes] = useState<ExperimentTypeDTO[]>([]);
  const [selectedType, setSelectedType] = useState<string>("");
  const [values, setValues] = useState<ParamValues>({});
  const [runs, setRuns] = useState<ExperimentRunDTO[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(() => {
    api.listExperiments().then(setRuns).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    api
      .experimentTypes()
      .then((t) => {
        setTypes(t);
        if (t.length > 0) {
          setSelectedType(t[0].name);
          setValues(defaultsFor(t[0].params));
        }
      })
      .catch((e) => setError(`Backend unreachable: ${e.message}`));
    loadRuns();
    const timer = window.setInterval(loadRuns, 3000);
    return () => window.clearInterval(timer);
  }, [loadRuns]);

  const type = types.find((t) => t.name === selectedType) ?? null;

  const pickType = (name: string) => {
    setSelectedType(name);
    const t = types.find((x) => x.name === name);
    setValues(defaultsFor(t?.params ?? []));
  };

  const start = async () => {
    if (!type) return;
    setBusy(true);
    setError(null);
    try {
      const params = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== null && v !== ""));
      const run = await api.startExperiment(type.name, params);
      loadRuns();
      onPick(run.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <h2>Experiments</h2>
      <p className="muted">
        Reproducible benchmarks behind the report's evaluation sections: ablations, tournaments,
        prediction accuracy, archetype discovery, rule extraction, and latency profiling. Runs
        execute on the backend and are stored in the ledger.
      </p>
      {error && <div className="error-banner">{error}</div>}

      <div className="two-col two-col-wide">
        <div className="stack">
          <div className="card">
            <h3>Launch</h3>
            {types.length === 0 ? (
              <p className="muted small">No experiment types available.</p>
            ) : (
              <>
                <div className="type-grid">
                  {types.map((t) => (
                    <button
                      key={t.name}
                      className={`type-card${t.name === selectedType ? " type-card-active" : ""}`}
                      onClick={() => pickType(t.name)}
                      type="button"
                    >
                      <div className="type-title">{t.title}</div>
                      {t.report_section && <div className="small muted">{t.report_section}</div>}
                    </button>
                  ))}
                </div>
                {type && (
                  <div className="type-detail">
                    <p className="small">{type.description}</p>
                    {type.estimated && <p className="small muted">Estimated: {type.estimated}</p>}
                    <ParamForm
                      params={type.params}
                      values={values}
                      onChange={(name, v) => setValues({ ...values, [name]: v })}
                    />
                    <button className="btn-primary" onClick={start} disabled={busy} type="button">
                      {busy ? "Starting…" : `Run ${type.title}`}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="card">
            <h3>Runs</h3>
            {runs.length === 0 ? (
              <p className="muted small">No runs yet.</p>
            ) : (
              <div className="run-list">
                {runs.map((r) => {
                  const p = r.progress ?? { done: 0, total: 0 };
                  const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : r.status === "completed" ? 100 : 0;
                  return (
                    <button
                      key={r.id}
                      className={`run-item${r.id === runId ? " run-item-active" : ""}`}
                      onClick={() => onPick(r.id)}
                      type="button"
                    >
                      <div className="run-item-head">
                        <span>{r.title || titleCase(r.kind)}</span>
                        <StatusBadge status={r.status} />
                      </div>
                      <div className="bar-track bar-track-sm">
                        <div className="bar-fill" style={{ width: `${pct}%` }} />
                      </div>
                      <div className="small muted">
                        {formatTime(r.created_at)} · {titleCase(r.kind)}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div>
          {runId ? (
            <RunDetail runId={runId} onChanged={loadRuns} />
          ) : (
            <div className="card empty-state">
              <p className="muted">Select a run to see its progress and results, or launch a new one.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
