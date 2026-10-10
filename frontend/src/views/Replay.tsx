import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { Board } from "../components/Board";
import { RoundTable } from "../components/RoundTable";
import { XaiPanel } from "../components/XaiPanel";
import type { HistoryResponse, SessionSummaryDTO, TurnRecordDTO } from "../types";
import { describeAction } from "../types";

const SPEEDS = [
  { label: "0.5×", ms: 2000 },
  { label: "1×", ms: 1000 },
  { label: "2×", ms: 500 },
  { label: "4×", ms: 250 },
];

export function Replay({
  sessionId,
  onPick,
}: {
  sessionId: string | null;
  onPick: (id: string) => void;
}) {
  const [sessions, setSessions] = useState<SessionSummaryDTO[]>([]);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1000);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    api
      .listSessions()
      .then((list) => {
        setSessions(list);
        if (!sessionId && list.length > 0) onPick(list[0].id);
      })
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    setHistory(null);
    setPlaying(false);
    api
      .getHistory(sessionId)
      .then((h) => {
        setHistory(h);
        setStep(0);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [sessionId]);

  const moves: TurnRecordDTO[] = history?.moves ?? [];

  useEffect(() => {
    if (!playing) return;
    timer.current = window.setInterval(() => {
      setStep((s) => {
        if (s >= moves.length - 1) {
          setPlaying(false);
          return s;
        }
        return s + 1;
      });
    }, speed);
    return () => window.clearInterval(timer.current);
  }, [playing, speed, moves.length]);

  const current = moves[step] ?? null;
  const state = current?.state_after ?? current?.state_before ?? null;
  const playerNames = state?.players.map((p) => p.name) ?? history?.session.players.map((p) => p.name) ?? [];
  const roundStarts = new Map<number, number>();
  moves.forEach((m, i) => {
    if (!roundStarts.has(m.round)) roundStarts.set(m.round, i);
  });

  return (
    <div className="page monitor-view">
      <div className="monitor-header">
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
        {sessionId && (
          <>
            <a className="btn-ghost" href={`#/monitor/${sessionId}`}>
              monitor
            </a>
            <a className="btn-ghost" href={`#/profiles/${sessionId}`}>
              profiles
            </a>
            <a className="btn-ghost" href={api.exportUrl(sessionId)}>
              export JSON
            </a>
          </>
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {!history && sessionId && !error && <p className="muted">Loading history…</p>}
      {history && moves.length === 0 && <p className="muted">This session has no recorded moves.</p>}

      {moves.length > 0 && (
        <>
          <div className="replay-controls">
            <button className="btn-ghost" onClick={() => setStep(0)} disabled={step === 0}>
              ⏮
            </button>
            <button className="btn-ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>
              ◀
            </button>
            <button
              className="btn-ghost"
              onClick={() => {
                if (!playing && step >= moves.length - 1) setStep(0);
                setPlaying(!playing);
              }}
            >
              {playing ? "❚❚" : "▶ play"}
            </button>
            <button
              className="btn-ghost"
              onClick={() => setStep((s) => Math.min(moves.length - 1, s + 1))}
              disabled={step === moves.length - 1}
            >
              ▶
            </button>
            <button className="btn-ghost" onClick={() => setStep(moves.length - 1)} disabled={step === moves.length - 1}>
              ⏭
            </button>
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} title="playback speed">
              {SPEEDS.map((s) => (
                <option key={s.ms} value={s.ms}>
                  {s.label}
                </option>
              ))}
            </select>
            <input
              type="range"
              min={0}
              max={moves.length - 1}
              value={step}
              onChange={(e) => setStep(Number(e.target.value))}
            />
            <span className="small muted">
              move {step + 1}/{moves.length} — round {current?.round}:{" "}
              {current ? `${current.player_name} ${describeAction(current.action)}` : ""}
            </span>
          </div>
          <div className="round-jumps">
            <span className="small muted">jump to round:</span>
            {[...roundStarts.entries()].map(([round, index]) => (
              <button
                key={round}
                className={`btn-ghost${current?.round === round ? " btn-active" : ""}`}
                onClick={() => setStep(index)}
              >
                {round}
              </button>
            ))}
          </div>
          <div className="monitor-body">
            <div className="monitor-main">
              {state ? <Board state={state} /> : <p className="muted">No board snapshot on this move.</p>}
              <h3>Rounds</h3>
              <div className="table-scroll">
                <RoundTable
                  rounds={history?.rounds ?? []}
                  players={playerNames}
                  onJump={(round) => {
                    const idx = roundStarts.get(round);
                    if (idx !== undefined) setStep(idx);
                  }}
                />
              </div>
            </div>
            <XaiPanel record={current} />
          </div>
        </>
      )}
    </div>
  );
}
