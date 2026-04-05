import { useEffect, useState } from 'react';
import { api, type Session } from '../api/client';

const TILE_DOTS: Record<string, string> = {
  blue: 'bg-[#67c0dd]',
  yellow: 'bg-[#ffff59]',
  red: 'bg-[#f08080]',
  black: 'bg-[#90ee90]',
  white: 'bg-white',
};

interface ProfileResult {
  summary: string;
  player_name: string;
  total_moves: number;
  final_score: number;
  style: string;
  color_preferences: Record<string, number>;
  source_split: { factory: number; center: number };
  destination_split: { pattern_line: number; floor: number };
  row_preferences: Record<string, number>;
  timing: { avg_total_ms: number; avg_decide_ms: number };
  score_trajectory: number[];
  analyzer: string;
}

export default function ProfileAnalyzer({ sessionId, session }: {
  sessionId: string;
  session: Session | null;
}) {
  const [analyzers, setAnalyzers] = useState<{ name: string; description: string }[]>([]);
  const [selectedAnalyzer, setSelectedAnalyzer] = useState('BasicProfileAnalyzer');
  const [selectedPlayers, setSelectedPlayers] = useState<Set<string>>(new Set());
  const [profiles, setProfiles] = useState<Record<string, ProfileResult>>({});
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const playerNames = session?.player_config.map((p) => p.name || p.type) || [];

  useEffect(() => {
    api.profiler.listAnalyzers().then((d) => setAnalyzers(d.analyzers)).catch(() => {});
  }, []);

  useEffect(() => {
    setProfiles({});
    setSelectedPlayers(new Set());
  }, [sessionId]);

  async function runAnalysis() {
    if (selectedPlayers.size === 0) {
      setError('Select at least one player to analyze');
      return;
    }
    setError(null);

    for (const name of selectedPlayers) {
      setLoading(name);
      try {
        const result = await api.profiler.analyze(sessionId, name, selectedAnalyzer);
        setProfiles((prev) => ({ ...prev, [name]: result as unknown as ProfileResult }));
      } catch (e: any) {
        setError(e.message);
      }
    }
    setLoading(null);
  }

  return (
    <div className="space-y-6">
      {/* Config */}
      <div className="bg-gray-900 rounded-xl p-4 border border-gray-800 space-y-4">
        <h3 className="text-sm font-semibold text-teal-400">Profile Analysis</h3>

        {/* Analyzer selection */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">Analyzer</label>
          <select
            value={selectedAnalyzer}
            onChange={(e) => setSelectedAnalyzer(e.target.value)}
            className="w-full bg-gray-800 text-gray-200 rounded-lg px-3 py-2 text-sm border border-gray-700"
          >
            {analyzers.map((a) => (
              <option key={a.name} value={a.name}>{a.name} — {a.description}</option>
            ))}
          </select>
        </div>

        {/* Player selection */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">Players to analyze</label>
          <div className="flex gap-3 flex-wrap">
            {playerNames.map((name) => (
              <label key={name} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={selectedPlayers.has(name)}
                  onChange={(e) => {
                    const next = new Set(selectedPlayers);
                    e.target.checked ? next.add(name) : next.delete(name);
                    setSelectedPlayers(next);
                  }}
                  className="rounded border-gray-600 bg-gray-800 text-teal-500"
                />
                <span className="text-sm text-gray-300">{name}</span>
              </label>
            ))}
          </div>
        </div>

        <button
          onClick={runAnalysis}
          disabled={selectedPlayers.size === 0 || loading !== null}
          className="px-4 py-2 bg-teal-600 hover:bg-teal-500 rounded-lg text-sm font-medium transition disabled:opacity-50"
        >
          {loading ? `Analyzing ${loading}...` : 'Analyze'}
        </button>

        {error && (
          <div className="text-xs text-red-400">{error}</div>
        )}
      </div>

      {/* Results */}
      {Object.entries(profiles).map(([name, profile]) => (
        <div key={name} className="bg-gray-900 rounded-xl p-4 border border-gray-800 space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-base font-semibold text-teal-300">{name}</h3>
            <span className="text-lg font-bold text-teal-400">{profile.final_score} pts</span>
          </div>

          {/* Summary */}
          <p className="text-sm text-gray-300 leading-relaxed">{profile.summary}</p>

          {/* Stats grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="bg-gray-800 rounded-lg p-3 text-center">
              <div className="text-[10px] text-gray-500">Total Moves</div>
              <div className="text-lg font-bold text-gray-200">{profile.total_moves}</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-3 text-center">
              <div className="text-[10px] text-gray-500">Play Style</div>
              <div className="text-sm font-medium text-yellow-300 capitalize">{profile.style}</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-3 text-center">
              <div className="text-[10px] text-gray-500">Avg Decision</div>
              <div className="text-lg font-bold text-blue-300">{profile.timing.avg_decide_ms}ms</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-3 text-center">
              <div className="text-[10px] text-gray-500">Floor Usage</div>
              <div className="text-lg font-bold text-red-300">{profile.destination_split.floor}%</div>
            </div>
          </div>

          {/* Color preferences */}
          <div>
            <div className="text-xs text-gray-500 mb-2">Color Preferences</div>
            <div className="flex gap-2">
              {Object.entries(profile.color_preferences).map(([color, pct]) => (
                <div key={color} className="flex items-center gap-1.5 bg-gray-800 rounded px-2 py-1">
                  <div className={`w-3 h-3 rounded-sm ${TILE_DOTS[color] || 'bg-gray-500'}`} />
                  <span className="text-xs text-gray-300 capitalize">{color}</span>
                  <span className="text-xs text-gray-500">{pct}%</span>
                </div>
              ))}
            </div>
          </div>

          {/* Source split bar */}
          <div>
            <div className="text-xs text-gray-500 mb-1">Source Split</div>
            <div className="flex h-4 rounded-full overflow-hidden">
              <div className="bg-teal-600 flex items-center justify-center text-[9px] text-white"
                   style={{ width: `${profile.source_split.factory}%` }}>
                {profile.source_split.factory > 15 && `Factory ${profile.source_split.factory}%`}
              </div>
              <div className="bg-yellow-600 flex items-center justify-center text-[9px] text-white"
                   style={{ width: `${profile.source_split.center}%` }}>
                {profile.source_split.center > 15 && `Center ${profile.source_split.center}%`}
              </div>
            </div>
          </div>

          {/* Score trajectory */}
          {profile.score_trajectory.length > 0 && (
            <div>
              <div className="text-xs text-gray-500 mb-1">Score Trajectory</div>
              <div className="flex items-end gap-px h-12">
                {profile.score_trajectory.map((s, i) => {
                  const max = Math.max(...profile.score_trajectory, 1);
                  const h = Math.max(2, (s / max) * 48);
                  return (
                    <div
                      key={i}
                      className="bg-teal-500/60 rounded-t-sm flex-1 min-w-[2px]"
                      style={{ height: `${h}px` }}
                      title={`Move ${i + 1}: ${s} pts`}
                    />
                  );
                })}
              </div>
            </div>
          )}

          <div className="text-[10px] text-gray-600">
            Analyzed by {profile.analyzer}
          </div>
        </div>
      ))}
    </div>
  );
}
