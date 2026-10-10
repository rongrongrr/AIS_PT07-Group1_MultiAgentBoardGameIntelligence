import { useCallback, useEffect, useRef, useState } from "react";
import { api, connectSessionWs } from "../api/client";
import { Board } from "../components/Board";
import { MoveLog } from "../components/MoveLog";
import { XaiPanel } from "../components/XaiPanel";
import type {
  GameStateDTO,
  SessionDetailDTO,
  SessionSummaryDTO,
  TurnRecordDTO,
  WsEvent,
} from "../types";

function SessionPicker({
  onPick,
}: {
  onPick: (id: string) => void;
}) {
  const [sessions, setSessions] = useState<SessionSummaryDTO[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listSessions()
      .then(setSessions)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="config-view">
      <h2>Monitor a session</h2>
      {error && <div className="error-banner">Backend unreachable: {error}</div>}
      {sessions.length === 0 && !error && (
        <p className="muted">No sessions yet — create one first.</p>
      )}
      <div className="session-list">
        {sessions.map((s) => (
          <button key={s.id} className="session-item" onClick={() => onPick(s.id)}>
            <span className="mono small">{s.id}</span>
            <span className={`status-badge status-${s.status}`}>{s.status}</span>
            <span className="small">
              {s.players.map((p) => `${p.name} (${p.tactician})`).join(" vs ")}
            </span>
            {s.scores && (
              <span className="small muted">{s.scores.join(" : ")}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

export function LiveMonitor({
  sessionId,
  onPick,
}: {
  sessionId: string | null;
  onPick: (id: string) => void;
}) {
  const [session, setSession] = useState<SessionDetailDTO | null>(null);
  const [state, setState] = useState<GameStateDTO | null>(null);
  const [moves, setMoves] = useState<TurnRecordDTO[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [wsStatus, setWsStatus] = useState("connecting");
  const [gameOver, setGameOver] = useState<{
    winner: number;
    scores: number[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | undefined>(undefined);

  const handleEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case "status":
        setSession((s) => (s ? { ...s, status: event.status } : s));
        break;
      case "state":
        setState(event.state);
        break;
      case "move":
        setMoves((m) => [...m.filter((x) => x.step !== event.record.step), event.record]);
        if (event.record.state_after) setState(event.record.state_after);
        break;
      case "round":
        break;
      case "game_over":
        setGameOver({ winner: event.winner, scores: event.scores });
        break;
      case "log":
        setLogs((l) => [...l.slice(-199), event.message]);
        break;
    }
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    setSession(null);
    setState(null);
    setMoves([]);
    setGameOver(null);
    setError(null);

    api
      .getSession(sessionId)
      .then((s) => {
        setSession(s);
        if (s.state) setState(s.state);
      })
      .catch((e) => setError(e.message));
    // Preload any history (e.g. reconnecting to a running/finished game).
    api
      .getHistory(sessionId)
      .then((h) => setMoves(h.moves))
      .catch(() => undefined);

    const ws = connectSessionWs(sessionId, handleEvent, setWsStatus);
    return () => ws.close();
  }, [sessionId, handleEvent]);

  // Poll as a fallback while the socket is not open.
  useEffect(() => {
    if (!sessionId) return;
    pollRef.current = window.setInterval(() => {
      if (wsStatus !== "open") {
        api
          .getSession(sessionId)
          .then((s) => {
            setSession(s);
            if (s.state) setState(s.state);
          })
          .catch(() => undefined);
      }
    }, 3000);
    return () => window.clearInterval(pollRef.current);
  }, [sessionId, wsStatus]);

  if (!sessionId) return <SessionPicker onPick={onPick} />;

  const lastMove =
    moves.length > 0
      ? moves.reduce((a, b) => (a.step > b.step ? a : b))
      : null;

  return (
    <div className="monitor-view">
      <div className="monitor-header">
        <span className="mono small">{sessionId}</span>
        {session && (
          <span className={`status-badge status-${session.status}`}>
            {session.status}
          </span>
        )}
        <span className={`ws-dot ws-${wsStatus}`} title={`ws: ${wsStatus}`} />
        {session?.room_url && (
          <a href={session.room_url} target="_blank" rel="noreferrer">
            join link ↗
          </a>
        )}
        <span className="spacer" />
        {session?.status === "running" && (
          <button
            className="btn-ghost"
            onClick={() => api.stopSession(sessionId).catch(() => undefined)}
          >
            stop
          </button>
        )}
        <a className="btn-ghost" href={api.exportUrl(sessionId)}>
          export JSON
        </a>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {gameOver && state && (
        <div className="winner-banner">
          🏆 {state.players[gameOver.winner]?.name ?? `player ${gameOver.winner + 1}`}{" "}
          wins — final scores {gameOver.scores.join(" : ")}
        </div>
      )}

      <div className="monitor-body">
        <div className="monitor-main">
          {state ? (
            <Board state={state} />
          ) : (
            <p className="muted">Waiting for game state…</p>
          )}
          <h3>Move log</h3>
          <MoveLog moves={moves} />
          {logs.length > 0 && (
            <details>
              <summary>System log</summary>
              <pre className="system-log">{logs.join("\n")}</pre>
            </details>
          )}
        </div>
        <XaiPanel record={lastMove} />
      </div>
    </div>
  );
}
