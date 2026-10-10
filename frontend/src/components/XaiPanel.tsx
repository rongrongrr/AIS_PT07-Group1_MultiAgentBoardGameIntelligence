import { titleCase } from "../format";
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
        <span className="muted small"> · {titleCase(record.tactician)} · Step {record.step}</span>
      </div>
      {record.explanation ? (
        <>
          <p className="explanation-text">{record.explanation.text}</p>
          {record.explanation.concepts.length > 0 && (
            <div className="concept-chips">
              {record.explanation.concepts.map((c) => (
                <span key={c} className="concept-chip">
                  {titleCase(c)}
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
              <span className="muted small"> · {report.simulations} Sims</span>
            )}
            {report.used_opponent_model && (
              <span className="concept-chip" title="search biased by profiler">
                Opponent-Aware
              </span>
            )}
          </h4>
          <table className="candidates-table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Score</th>
                <th>Visits</th>
                <th>Prior</th>
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
        <span>Decide {timing.decide_ms?.toFixed(1) ?? "?"} ms</span>
        <span>Validate {timing.validate_ms?.toFixed(1) ?? "?"} ms</span>
        {timing.execute_ms != null && <span>Execute {timing.execute_ms.toFixed(0)} ms</span>}
        <span>Explain {timing.explain_ms?.toFixed(1) ?? "?"} ms</span>
        {validation && (
          <span className={validation.ok ? "ok-text" : "error-text"}>
            Validator {validation.ok ? "OK" : "Rejected"}
            {validation.attempts && validation.attempts > 1
              ? ` After ${validation.attempts} attempts`
              : ""}
            {validation.site_fallback ? " · Site Fallback" : ""}
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
