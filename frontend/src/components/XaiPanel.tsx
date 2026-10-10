import type { TurnRecordDTO } from "../types";
import { describeAction, sameAction } from "../types";
import { ProfileCard } from "./ProfileCard";

export function XaiPanel({ record }: { record: TurnRecordDTO | null }) {
  if (!record) {
    return (
      <aside className="xai-panel">
        <h3>Explainability</h3>
        <p className="muted">
          No moves yet. Once the game starts, each decision appears here with
          the Tactician's reasoning, considered alternatives, and opponent
          profiles.
        </p>
      </aside>
    );
  }

  const report = record.report;
  const chosen = record.action;
  const pv =
    report?.candidates.find((c) => sameAction(c.action, chosen))
      ?.principal_variation ?? [];
  const profiles = Object.values(record.profiles ?? {});
  const timing = record.timing ?? {};
  const validation = record.validation;

  return (
    <aside className="xai-panel">
      <h3>Why this move</h3>
      <div className="chosen-action">
        <span className="player-name">{record.player_name}</span>{" "}
        <span className="action-chip action-chip-primary">
          {describeAction(chosen)}
        </span>
        <span className="muted small"> · {record.tactician} · step {record.step}</span>
      </div>
      {record.explanation ? (
        <>
          <p className="explanation-text">{record.explanation.text}</p>
          {record.explanation.concepts.length > 0 && (
            <div className="concept-chips">
              {record.explanation.concepts.map((c) => (
                <span key={c} className="concept-chip">
                  {c.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          )}
        </>
      ) : (
        <p className="muted small">No explanation attached to this move.</p>
      )}

      {report && report.candidates.length > 0 && (
        <>
          <h4>
            Alternatives considered
            {report.simulations > 0 && (
              <span className="muted small"> · {report.simulations} sims</span>
            )}
            {report.used_opponent_model && (
              <span className="concept-chip" title="search biased by profiler">
                opponent-aware
              </span>
            )}
          </h4>
          <table className="candidates-table">
            <thead>
              <tr>
                <th>action</th>
                <th>score</th>
                <th>visits</th>
                <th>prior</th>
              </tr>
            </thead>
            <tbody>
              {report.candidates.slice(0, 6).map((c, i) => (
                <tr
                  key={i}
                  className={sameAction(c.action, chosen) ? "row-chosen" : ""}
                >
                  <td>{describeAction(c.action)}</td>
                  <td>{c.score.toFixed(2)}</td>
                  <td>{c.visits || "—"}</td>
                  <td>{c.prior ? c.prior.toFixed(2) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {pv.length > 1 && (
        <>
          <h4>Expected line</h4>
          <div className="pv-chips">
            {pv.slice(0, 5).map((a, i) => (
              <span key={i} className="action-chip">
                {i + 1}. {describeAction(a)}
              </span>
            ))}
          </div>
        </>
      )}

      <h4>Pipeline</h4>
      <div className="small muted timing-row">
        <span>decide {timing.decide_ms?.toFixed(1) ?? "?"} ms</span>
        <span>validate {timing.validate_ms?.toFixed(1) ?? "?"} ms</span>
        {timing.execute_ms != null && <span>execute {timing.execute_ms.toFixed(0)} ms</span>}
        <span>explain {timing.explain_ms?.toFixed(1) ?? "?"} ms</span>
        {validation && (
          <span className={validation.ok ? "ok-text" : "error-text"}>
            validator {validation.ok ? "ok" : "rejected"}
            {validation.attempts && validation.attempts > 1
              ? ` after ${validation.attempts} attempts`
              : ""}
            {validation.site_fallback ? " · site fallback" : ""}
          </span>
        )}
      </div>

      {profiles.length > 0 && (
        <>
          <h4>Opponent profiles</h4>
          {profiles.map((p) => (
            <ProfileCard key={p.player_index} profile={p} />
          ))}
        </>
      )}
    </aside>
  );
}
