import { useEffect, useRef, useState } from "react";
import type { LogEntry } from "../types";

const LEVELS = ["all", "info", "warning", "error"];

export function SystemLog({ entries }: { entries: LogEntry[] }) {
  const [level, setLevel] = useState("all");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries.length]);

  const visible =
    level === "all" ? entries : entries.filter((e) => e.level === level);

  return (
    <div className="syslog">
      <div className="syslog-header">
        <span className="small muted">System log · {entries.length}</span>
        <select value={level} onChange={(e) => setLevel(e.target.value)}>
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
      </div>
      <div className="syslog-body" ref={ref}>
        {visible.length === 0 ? (
          <div className="muted small">No log entries.</div>
        ) : (
          visible.map((e, i) => (
            <div key={i} className={`syslog-line level-${e.level}`}>
              <span className="syslog-ts">{e.ts}</span>
              <span className="syslog-level">{e.level}</span>
              {e.player && <span className="syslog-player">{e.player}</span>}
              {e.phase && <span className="syslog-phase">{e.phase}</span>}
              <span>{e.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
