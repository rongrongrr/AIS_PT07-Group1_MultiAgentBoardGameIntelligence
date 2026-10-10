import { useEffect, useState } from 'react';
import { api, type TournamentResults } from '../api/client';

/** Elo ranking and win-rate matrix from the latest saved round-robin (scripts/elo_tournament.py --save). */
export default function Leaderboard() {
  const [data, setData] = useState<TournamentResults | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.tournament.latest().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="text-red-400 text-sm">{error}</div>;
  if (!data) return <div className="text-gray-500 text-sm">Loading...</div>;
  if (!data.available || !data.ranking) {
    return (
      <div className="text-gray-500 text-sm">
        No tournament results saved yet. Run <code>python scripts/elo_tournament.py --save models/elo_results.json</code>.
      </div>
    );
  }
  const names = data.ranking.map((r) => r.player);
  const cell = (p: number | undefined) =>
    p === undefined ? 'bg-gray-900' : p >= 0.6 ? 'bg-teal-900/60' : p <= 0.4 ? 'bg-red-900/40' : 'bg-gray-800';

  return (
    <div className="space-y-6" data-testid="leaderboard">
      <div>
        <h3 className="text-sm font-semibold text-teal-400">Elo ranking</h3>
        <p className="text-xs text-gray-500">
          {data.games} simulated games, {data.deals_per_pair} deals per pair from both seats ({data.generated}). Small samples:
          differences of under about 100 Elo are within noise.
        </p>
      </div>
      <table className="w-full text-sm">
        <thead className="text-xs text-gray-500">
          <tr><th className="text-left">#</th><th className="text-left">Player</th><th className="text-right">Elo</th><th className="text-right">Mean score</th></tr>
        </thead>
        <tbody>
          {data.ranking.map((r, i) => (
            <tr key={r.player} className="border-t border-gray-800">
              <td>{i + 1}</td><td className="font-medium text-gray-200">{r.player}</td>
              <td className="text-right">{r.elo}</td><td className="text-right">{r.mean_score}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div>
        <h3 className="text-sm font-semibold text-teal-400 mb-1">Win rate of row against column</h3>
        <div className="overflow-x-auto">
          <table className="text-xs">
            <thead>
              <tr><th />{names.map((n) => <th key={n} className="px-2 text-gray-500 font-normal">{n.slice(0, 10)}</th>)}</tr>
            </thead>
            <tbody>
              {names.map((row) => (
                <tr key={row}>
                  <th className="text-left pr-2 text-gray-400 font-normal">{row}</th>
                  {names.map((col) => {
                    const p = data.win_rates?.[row]?.[col];
                    return <td key={col} className={`text-center px-2 py-1 ${cell(p)}`}>{row === col ? '-' : p?.toFixed(2)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
