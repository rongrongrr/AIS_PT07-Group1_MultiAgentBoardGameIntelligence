import { useCallback, useEffect, useState } from "react";
import { api, connectSessionWs, type WsStatus } from "../api/client";
import { Board } from "../components/Board";
import { MoveLog } from "../components/MoveLog";
import { RoundTable } from "../components/RoundTable";
import { SessionCard, isRunning } from "../components/SessionCard";
import { StatusBadge } from "../components/StatusBadge";
import { SystemLog } from "../components/SystemLog";
import { XaiPanel } from "../components/XaiPanel";
import type {
  GameStateDTO,
  LogEntry,
  RoundResultDTO,
  SessionDetailDTO,
  SessionSummaryDTO,
  TurnRecordDTO,
  WsEvent,
} from "../types";

function SessionPicker() {
  const [sessions, setSessions] = useState<SessionSummaryDTO[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listSessions().then(setSessions).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="page">
      <h2>Monitor a session</h2>
      {error && <div className="error-banner">Backend unreachable: {error}</div>}
      {sessions.length === 0 && !error && (
        <p className="muted">No sessions yet — create one first.</p>
      )}
      <div className="session-list">
        {sessions.map((s) => (
          <SessionCard key={s.id} session={s} />
        ))}
      </div>
    </div>
  );
}

interface LiveStatus {
  status: string;
  roomUrl?: string;
  roomName?: string;
  waiting?: string[];
}

export function Monitor({ sessionId }: { sessionId: string | null }) {
  const [session, setSession] = useState<SessionDetailDTO | null>(null);
  const [state, setState] = useState<GameStateDTO | null>(null);
  const [moves, setMoves] = useState<TurnRecordDTO[]>([]);
  const [rounds, setRounds] = useState<RoundResultDTO[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [live, setLive] = useState<LiveStatus | null>(null);
  const [wsStatus, setWsStatus] = useState<WsStatus>("connecting");
  const [selected, setSelected] = useState<TurnRecordDTO | null>(null);
  const [gameOver, setGameOver] = useState<{ winner: number; scores: number[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);

  const handleEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case "status":
        setSession((s) => (s ? { ...s, status: event.status, room_url: event.room_url ?? s.room_url } : s));
        setLive({ status: event.status, roomUrl: event.room_url, roomName: event.room_name, waiting: event.waiting_for_humans });
        break;
      case "state":
        setState(event.state);
        break;
      case "move":
        setMoves((m) => [...m.filter((x) => x.step !== event.record.step), event.record]);
        setSelected(null);
        if (event.record.state_after) setState(event.record.state_after);
        break;
      case "round":
        setRounds((r) => [...r.filter((x) => x.round !== event.result.round), event.result]);
        break;
      case "game_over":
        setGameOver({ winner: event.winner, scores: event.scores });
        break;
      case "log":
        setLogs((l) => [
          ...l.slice(-299),
          {
            ts: new Date().toLocaleTimeString(),
            level: event.level,
            message: event.message,
            phase: event.phase,
            player: event.player,
          },
        ]);
        break;
    }
  }, []);

  const refresh = useCallback(() => {
    if (!sessionId) return;
    api
      .getSession(sessionId)
      .then((s) => {
        setSession(s);
        if (s.state) setState(s.state);
        if (s.result && s.result.scores) {
          setGameOver((g) => g ?? (s.status === "completed" ? { winner: s.result!.winner, scores: s.result!.scores } : null));
        }
        setError(null);
      })
      .catch((e) => setError(e.message));
    api
      .getHistory(sessionId)
      .then((h) => {
        setMoves(h.moves);
        if (h.rounds) setRounds(h.rounds);
      })
      .catch(() => undefined);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    setSession(null);
    setState(null);
    setMoves([]);
    setRounds([]);
    setLogs([]);
    setLive(null);
    setSelected(null);
    setGameOver(null);
    setError(null);
    setStopping(false);
    refresh();
    const ws = connectSessionWs(sessionId, handleEvent, setWsStatus);
    return () => ws.close();
  }, [sessionId, handleEvent, refresh]);

  // Poll as a fallback while the socket is not open.
  useEffect(() => {
    if (!sessionId || wsStatus === "open") return;
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [sessionId, wsStatus, refresh]);

  if (!sessionId) return <SessionPicker />;

  const lastMove =
    moves.length > 0 ? moves.reduce((a, b) => (a.step > b.step ? a : b)) : null;
  const shown = selected ?? lastMove;
  const playerNames = state?.players.map((p) => p.name) ?? session?.players.map((p) => p.name) ?? [];
  const isLive = session?.mode === "live";
  const running = session != null && isRunning(session.status);

  const stop = () => {
    if (!sessionId) return;
    setStopping(true);
    api
      .stopSession(sessionId)
      .then(refresh)
      .catch((e) => {
        setStopping(false);
        setError(`stop failed: ${e.message}`);
      });
  };

  return (
    <div className="page monitor-view">
      <div className="monitor-header">
        <span className="mono small">{sessionId}</span>
        {session && <StatusBadge status={session.status} />}
        {session && <span className="mode-chip">{session.mode}</span>}
        <span className={`ws-dot ws-${wsStatus}`} title={`websocket: ${wsStatus}`} />
        {wsStatus !== "open" && <span className="small muted">polling</span>}
        <span className="spacer" />
        {running && (
          <button className="btn-ghost" onClick={stop} disabled={stopping}>
            {stopping ? "stopping…" : "stop"}
          </button>
        )}
        <a className="btn-ghost" href={`#/replay/${sessionId}`}>
          replay
        </a>
        <a className="btn-ghost" href={`#/profiles/${sessionId}`}>
          profiles
        </a>
        <a className="btn-ghost" href={api.exportUrl(sessionId)}>
          export JSON
        </a>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {session?.error && <div className="error-banner">{session.error}</div>}

      {(isLive || (live && live.status !== "running")) && (
        <div className={`live-strip live-${live?.status ?? session?.status ?? "created"}`}>
          <strong>{isLive ? "Live platform" : "Session"}</strong>
          <span>· {live?.status ?? session?.status}</span>
          {isLive && (live?.roomName ?? session?.room_name ?? session?.live?.room_name) && (
            <span>
              · room <code>{live?.roomName ?? session?.room_name ?? session?.live?.room_name}</code>
            </span>
          )}
          {(live?.roomUrl || session?.room_url) && (
            <a href={live?.roomUrl ?? session?.room_url ?? "#"} target="_blank" rel="noreferrer">
              join link ↗
            </a>
          )}
          {live?.waiting && live.waiting.length > 0 && (
            <span>· waiting for: {live.waiting.join(", ")}</span>
          )}
          {isLive && (
            <span className="muted small">
              humans: open the link (room pre-filled), enter a name, click Play — the host bot starts once everyone is in
            </span>
          )}
        </div>
      )}

      {state && (
        <div className="score-header">
          {state.players.map((p, i) => (
            <div
              key={i}
              className={`score-chip${state.current_player === i && state.phase === "drafting" ? " score-chip-active" : ""}`}
            >
              <span className="player-name">{p.name}</span>
              <span className="player-score">{p.score}</span>
              {session?.players[i] && <span className="muted small">{session.players[i].tactician}</span>}
            </div>
          ))}
          <span className="muted small">round {state.round}</span>
        </div>
      )}

      {gameOver && (
        <div className="winner-banner">
          🏆 {playerNames[gameOver.winner] ?? `player ${gameOver.winner + 1}`} wins — final scores{" "}
          {gameOver.scores.join(" : ")}
        </div>
      )}

      <div className="monitor-body">
        <div className="monitor-main">
          {state ? (
            <Board state={state} />
          ) : (
            <p className="muted">
              {session?.status === "created" ? "Session not started yet." : "Waiting for game state…"}
            </p>
          )}
          <h3>Move log</h3>
          <MoveLog moves={moves} selectedStep={shown?.step ?? null} onSelect={setSelected} />
          <h3>Rounds</h3>
          <div className="table-scroll">
            <RoundTable rounds={rounds} players={playerNames} />
          </div>
          <SystemLog entries={logs} />
        </div>
        <XaiPanel record={shown} />
      </div>
    </div>
  );
}
