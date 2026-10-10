import { useEffect, useMemo, useRef, useState } from 'react';
import { api, type MoveResponse } from '../api/client';
import BoardSnapshot from './BoardSnapshot';
import FeedbackWidget from './FeedbackWidget';

const SPEEDS = [0.5, 1, 2, 4];

/** ?explain=scores shows only the move scores (control condition for the explanation study). */
function scoresOnly(): boolean {
  try { return new URLSearchParams(window.location.search).get('explain') === 'scores'; } catch { return false; }
}

/** Step through a recorded game with playback controls: play/pause, prev/next, jump, speed. */
export default function Replay({ sessionId }: { sessionId: string }) {
  const [moves, setMoves] = useState<MoveResponse[]>([]);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setMoves([]); setIdx(0); setPlaying(false); setError(null);
    api.history.get(sessionId)
      .then((d) => setMoves(d.moves.filter((m) => m.board)))
      .catch((e) => setError(e.message));
  }, [sessionId]);

  useEffect(() => {
    if (timer.current) clearInterval(timer.current);
    if (!playing) return;
    timer.current = setInterval(() => {
      setIdx((i) => {
        if (i >= moves.length - 1) { setPlaying(false); return i; }
        return i + 1;
      });
    }, 1200 / speed);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [playing, speed, moves.length]);

  // first move of each round, for "jump to round" (rounds are inferred from the board refill)
  const roundStarts = useMemo(() => {
    const starts = [0];
    let prev = -1;
    moves.forEach((m, i) => {
      const t = m.board
        ? m.board.factories.reduce((s, f) => s + f.length, 0) + m.board.center_pool.filter((x) => x !== 'firstPlayer').length
        : -1;
      if (prev >= 0 && t > prev + 5) starts.push(i);
      if (t >= 0) prev = t;
    });
    return starts;
  }, [moves]);

  if (error) return <div className="text-red-400 text-sm">{error}</div>;
  if (moves.length === 0) return <div className="text-gray-500 text-sm">No recorded moves with board snapshots for this session.</div>;

  const m = moves[idx];
  const go = (n: number) => setIdx(Math.max(0, Math.min(moves.length - 1, n)));
  const btn = 'px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded text-sm disabled:opacity-40';

  return (
    <div className="space-y-4 max-w-3xl mx-auto" data-testid="replay">
      <div className="flex flex-wrap items-center gap-2">
        <button className={btn} onClick={() => go(0)} disabled={idx === 0} title="Jump to start">&#9198;</button>
        <button className={btn} onClick={() => go(idx - 1)} disabled={idx === 0}>&#9664; Prev</button>
        <button className={`${btn} bg-teal-700 hover:bg-teal-600`} onClick={() => setPlaying(!playing)}>
          {playing ? '\u23F8 Pause' : '\u25B6 Play'}
        </button>
        <button className={btn} onClick={() => go(idx + 1)} disabled={idx >= moves.length - 1}>Next &#9654;</button>
        <button className={btn} onClick={() => go(moves.length - 1)} disabled={idx >= moves.length - 1} title="Jump to end">&#9197;</button>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}
                className="bg-gray-800 text-xs rounded px-2 py-1.5 border border-gray-700">
          {SPEEDS.map((s) => <option key={s} value={s}>{s}x</option>)}
        </select>
        <select value={roundStarts.filter((s) => s <= idx).length - 1}
                onChange={(e) => go(roundStarts[Number(e.target.value)])}
                className="bg-gray-800 text-xs rounded px-2 py-1.5 border border-gray-700">
          {roundStarts.map((_, r) => <option key={r} value={r}>Round {r + 1}</option>)}
        </select>
        <span className="text-xs text-gray-500 ml-auto">Move {idx + 1} / {moves.length}</span>
      </div>

      <input type="range" min={0} max={moves.length - 1} value={idx} onChange={(e) => go(Number(e.target.value))}
             className="w-full accent-teal-500" aria-label="Jump to move" />

      <div className="text-sm">
        <span className="font-semibold text-teal-300">{m.player_name}</span>
        <span className="text-gray-500"> ({m.system_tag || 'unknown model'})</span>
        {m.commentary && !scoresOnly() && <span className="text-gray-400"> &mdash; {m.commentary}</span>}
      </div>

      <BoardSnapshot board={m.board!} action={m.action} activePlayer={m.player_name} />

      {m.explanation?.rationale && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 space-y-1">
          <div className="text-[10px] text-gray-500">Why this move</div>
          {scoresOnly() ? (
            <ul className="text-sm text-gray-300" data-testid="scores-only">
              {m.explanation.top_alternatives.map((alt, i) => (
                <li key={i}>
                  {alt.score.toFixed(1)} &mdash; {alt.action.color} from{' '}
                  {alt.action.source_type === 'factory' ? `factory ${(alt.action.source_index ?? 0) + 1}` : 'center'} to{' '}
                  {alt.action.destination === 'floor' ? 'floor' : `row ${(alt.action.destination_row ?? 0) + 1}`}
                  {i === 0 ? ' (chosen)' : ''}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-200 leading-relaxed">{m.explanation.rationale}</p>
          )}
          <FeedbackWidget sessionId={sessionId} stepId={m.step_id} />
        </div>
      )}
    </div>
  );
}
