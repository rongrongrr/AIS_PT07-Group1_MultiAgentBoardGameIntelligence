import type { GameAction } from '../api/client';

function label(a: GameAction): string {
  const from = a.source_type === 'factory' ? `F${(a.source_index ?? 0) + 1}` : 'Center';
  const to = a.destination === 'floor' ? 'Floor' : `Row ${(a.destination_row ?? 0) + 1}`;
  return `${a.color} ${from} → ${to}`;
}

/** The moves the bot weighed, as bars scaled to the best score; the chosen move is highlighted. */
export default function AlternativesChart({ alternatives, chosen }: {
  alternatives: { action: GameAction; score: number }[];
  chosen: GameAction;
}) {
  if (alternatives.length === 0) return null;
  const scores = alternatives.map((a) => a.score);
  const min = Math.min(...scores, 0);
  const span = Math.max(Math.max(...scores) - min, 1e-6);
  const same = (x: GameAction) => JSON.stringify(x) === JSON.stringify(chosen);
  return (
    <ul className="space-y-1" aria-label="Alternatives considered" data-testid="alternatives">
      {alternatives.map((alt, i) => {
        const isChosen = same(alt.action) || (i === 0 && !alternatives.some((a) => same(a.action)));
        return (
          <li key={i} className="text-xs">
            <div className="flex justify-between text-gray-300">
              <span className="capitalize">{label(alt.action)}{isChosen && <span className="ml-1 text-teal-300">(chosen)</span>}</span>
              <span className="tabular-nums text-gray-400">{alt.score.toFixed(1)}</span>
            </div>
            <div className="h-1.5 bg-gray-800 rounded">
              <div className={`h-1.5 rounded ${isChosen ? 'bg-teal-500' : 'bg-gray-500'}`}
                   style={{ width: `${Math.max(4, ((alt.score - min) / span) * 100)}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
