import { useEffect, useState } from 'react';
import { api, type PlayerInsight } from '../api/client';

/**
 * Real-time profiler observations for each player of a session.
 * Live mode re-reads the ledger every few seconds (and whenever `refreshKey` changes);
 * with `uptoStep` it shows the profile as it stood at that move (replay overlay).
 */
export default function ProfilerInsights({ sessionId, uptoStep, refreshKey, pollMs = 0, title = 'Profiler insights' }: {
  sessionId: string;
  uptoStep?: number;
  refreshKey?: number;
  pollMs?: number;
  title?: string;
}) {
  const [insights, setInsights] = useState<PlayerInsight[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => api.profiler.insights(sessionId, uptoStep)
      .then((d) => { if (!cancelled) { setInsights(d.insights); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e.message); });
    load();
    const t = pollMs > 0 ? setInterval(load, pollMs) : undefined;
    return () => { cancelled = true; if (t) clearInterval(t); };
  }, [sessionId, uptoStep, refreshKey, pollMs]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 space-y-2" data-testid="profiler-insights">
      <div className="text-[10px] text-gray-500">{title}</div>
      {error && <div className="text-xs text-red-400">{error}</div>}
      {!error && insights.length === 0 && <div className="text-xs text-gray-600">Waiting for moves...</div>}
      {insights.map((p) => (
        <div key={p.player_name} className="text-xs text-gray-300">
          <span className="font-semibold text-teal-300">{p.player_name}</span>
          <span className="text-gray-500"> ({p.moves_observed} moves)</span>
          {p.archetype && (
            <span className="text-yellow-300">
              {' '}&middot; {p.archetype.replace('Player', '')} {Math.round((p.archetype_confidence ?? 0) * 100)}%
            </span>
          )}
          {p.style && <span className="text-gray-400"> &middot; {p.style}</span>}
          <div className="text-gray-400 leading-snug">{p.summary}</div>
        </div>
      ))}
    </div>
  );
}
