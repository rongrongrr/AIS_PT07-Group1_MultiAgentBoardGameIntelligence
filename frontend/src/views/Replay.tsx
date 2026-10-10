import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Board } from "../components/Board";
import { XaiPanel } from "../components/XaiPanel";
import type {
  HistoryResponse,
  SessionSummaryDTO,
  TurnRecordDTO,
} from "../types";
import { describeAction } from "../types";

export function Replay() {
  const [sessions, setSessions] = useState<SessionSummaryDTO[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listSessions()
      .then((list) => {
        setSessions(list);
        if (list.length > 0 && !selected) setSelected(list[0].id);
      })
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    setHistory(null);
    api
      .getHistory(selected)
      .then((h) => {
        setHistory(h);
        setStep(Math.max(0, h.moves.length - 1));
      })
      .catch((e) => setError(e.message));
  }, [selected]);

  const moves: TurnRecordDTO[] = history?.moves ?? [];
  const current = moves[step] ?? null;
  const state = current?.state_after ?? current?.state_before ?? null;

  return (
    <div className="monitor-view">
      <div className="monitor-header">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="" disabled>
            pick a session…
          </option>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id} — {s.players.map((p) => p.name).join(" vs ")} ({s.status})
            </option>
          ))}
        </select>
        {selected && (
          <a className="btn-ghost" href={api.exportUrl(selected)}>
            export JSON
          </a>
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {!history && selected && !error && <p className="muted">Loading history…</p>}
      {history && moves.length === 0 && (
        <p className="muted">This session has no recorded moves.</p>
      )}

      {moves.length > 0 && (
        <>
          <div className="replay-controls">
            <button
              className="btn-ghost"
              onClick={() => setStep(0)}
              disabled={step === 0}
            >
              ⏮
            </button>
            <button
              className="btn-ghost"
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0}
            >
              ◀
            </button>
            <input
              type="range"
              min={0}
              max={moves.length - 1}
              value={step}
              onChange={(e) => setStep(Number(e.target.value))}
            />
            <button
              className="btn-ghost"
              onClick={() => setStep((s) => Math.min(moves.length - 1, s + 1))}
              disabled={step === moves.length - 1}
            >
              ▶
            </button>
            <button
              className="btn-ghost"
              onClick={() => setStep(moves.length - 1)}
              disabled={step === moves.length - 1}
            >
              ⏭
            </button>
            <span className="small muted">
              move {step + 1}/{moves.length} — round {current?.round}:{" "}
              {current ? `${current.player_name} ${describeAction(current.action)}` : ""}
            </span>
          </div>
          <div className="monitor-body">
            <div className="monitor-main">
              {state ? (
                <Board state={state} />
              ) : (
                <p className="muted">No board snapshot on this move.</p>
              )}
            </div>
            <XaiPanel record={current} />
          </div>
        </>
      )}
    </div>
  );
}
