import type { SessionSummaryDTO } from "../types";
import { formatTime, playersLabel } from "../types";
import { hrefFor } from "../router";
import { StatusBadge } from "./StatusBadge";

const RUNNING = new Set(["starting", "running", "connecting", "lobby"]);

export function isRunning(status: string): boolean {
  return RUNNING.has(status);
}

export function SessionCard({
  session,
  onStart,
  onStop,
  onDelete,
}: {
  session: SessionSummaryDTO;
  onStart?: (id: string) => void;
  onStop?: (id: string) => void;
  onDelete?: (id: string) => void;
}) {
  const running = isRunning(session.status);
  return (
    <div className="session-card">
      <div className="session-card-main">
        <div className="session-card-title">
          <span className="mono small">{session.id}</span>
          <StatusBadge status={session.status} />
          <span className="mode-chip">{session.mode}</span>
        </div>
        <div className="small">{playersLabel(session.players)}</div>
        <div className="small muted">
          {formatTime(session.created_at)}
          {session.steps != null && ` · ${session.steps} moves`}
          {session.scores && ` · ${session.scores.join(" : ")}`}
          {session.winner_name && ` · 🏆 ${session.winner_name}`}
        </div>
      </div>
      <div className="session-card-actions">
        <a className="btn-ghost" href={hrefFor("monitor", session.id)}>
          monitor
        </a>
        <a className="btn-ghost" href={hrefFor("replay", session.id)}>
          replay
        </a>
        {session.status === "created" && onStart && (
          <button className="btn-ghost" onClick={() => onStart(session.id)}>
            start
          </button>
        )}
        {running && onStop && (
          <button className="btn-ghost" onClick={() => onStop(session.id)}>
            stop
          </button>
        )}
        {!running && onDelete && (
          <button
            className="btn-ghost btn-danger"
            onClick={() => onDelete(session.id)}
            title="delete this session and its recorded moves"
          >
            delete
          </button>
        )}
      </div>
    </div>
  );
}
