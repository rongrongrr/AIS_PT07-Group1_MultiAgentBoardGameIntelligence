import { useState } from "react";
import type { TurnRecordDTO } from "../types";
import { describeAction } from "../types";

function MoveRow({ record }: { record: TurnRecordDTO }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className="move-row" onClick={() => setOpen(!open)}>
        <td className="muted small">{record.step}</td>
        <td>{record.player_name}</td>
        <td>
          <span className="action-chip">{describeAction(record.action)}</span>
        </td>
        <td className="muted small">{record.tactician}</td>
        <td className="muted small">
          {record.timing?.total_ms != null
            ? `${record.timing.total_ms.toFixed(0)} ms`
            : "—"}
        </td>
        <td className="muted small">{open ? "▾" : "▸"}</td>
      </tr>
      {open && (
        <tr className="move-detail">
          <td colSpan={6}>
            {record.explanation?.text && <p>{record.explanation.text}</p>}
            <div className="small muted">
              decide {record.timing?.decide_ms?.toFixed(1) ?? "?"} ms · validate{" "}
              {record.timing?.validate_ms?.toFixed(1) ?? "?"} ms · explain{" "}
              {record.timing?.explain_ms?.toFixed(1) ?? "?"} ms
              {record.validation && !record.validation.ok && (
                <span className="error-text">
                  {" "}
                  · rejected: {record.validation.violation?.message}
                </span>
              )}
              {record.validation?.attempts && record.validation.attempts > 1 && (
                <span> · attempts {record.validation.attempts}</span>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function MoveLog({ moves }: { moves: TurnRecordDTO[] }) {
  const rounds = new Map<number, TurnRecordDTO[]>();
  for (const m of moves) {
    const list = rounds.get(m.round) ?? [];
    list.push(m);
    rounds.set(m.round, list);
  }
  const roundNumbers = [...rounds.keys()].sort((a, b) => b - a);

  if (moves.length === 0) {
    return <p className="muted">No moves recorded yet.</p>;
  }

  return (
    <div className="move-log">
      {roundNumbers.map((round) => (
        <details key={round} open={round === roundNumbers[0]}>
          <summary>
            Round {round}
            <span className="muted small">
              {" "}
              · {rounds.get(round)!.length} moves
            </span>
          </summary>
          <table className="move-table">
            <tbody>
              {rounds
                .get(round)!
                .slice()
                .sort((a, b) => a.step - b.step)
                .map((m) => (
                  <MoveRow key={m.step} record={m} />
                ))}
            </tbody>
          </table>
        </details>
      ))}
    </div>
  );
}
