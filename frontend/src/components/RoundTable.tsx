import type { RoundResultDTO } from "../types";

/** Per-round scoring summary: wall tilings, floor penalties, running scores. */
export function RoundTable({
  rounds,
  players,
  onJump,
}: {
  rounds: RoundResultDTO[];
  players: string[];
  onJump?: (round: number) => void;
}) {
  if (rounds.length === 0) {
    return <p className="muted small">No rounds resolved yet.</p>;
  }
  return (
    <table className="data-table round-table">
      <thead>
        <tr>
          <th>round</th>
          {players.map((p) => (
            <th key={p}>{p}</th>
          ))}
          <th>tilings</th>
        </tr>
      </thead>
      <tbody>
        {rounds.map((r) => (
          <tr
            key={r.round}
            className={onJump ? "clickable" : undefined}
            onClick={onJump ? () => onJump(r.round) : undefined}
          >
            <td>
              {r.round}
              {r.game_over && <span className="muted small"> · final</span>}
            </td>
            {players.map((p, i) => {
              const gained = r.tilings
                .filter((t) => t.player_index === i)
                .reduce((s, t) => s + t.points, 0);
              const penalty = r.floor_penalties?.[i] ?? 0;
              return (
                <td key={p} className="num">
                  <strong>{r.scores?.[i] ?? "—"}</strong>
                  <span className="muted small">
                    {" "}
                    (+{gained}
                    {penalty ? ` ${penalty}` : ""})
                  </span>
                </td>
              );
            })}
            <td className="small muted">
              {r.tilings.length === 0
                ? "—"
                : r.tilings
                    .map((t) => `${players[t.player_index] ?? t.player_index}: ${t.color} r${t.row + 1} +${t.points}`)
                    .join(", ")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
