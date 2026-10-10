import { useEffect, useMemo, useRef, useState } from 'react';
import { api, type MoveResponse } from '../api/client';
import { readPref, usePref } from '../lib/prefs';
import AlternativesChart from './AlternativesChart';
import BoardSnapshot from './BoardSnapshot';
import FeedbackWidget from './FeedbackWidget';
import Help, { GLOSSARY } from './Help';
import ProfilerInsights from './ProfilerInsights';

const SPEEDS = [0.5, 1, 2, 4];

/** ?explain=scores forces the scores-only control condition of the explanation study. */
function urlScoresOnly(): boolean {
  try { return new URLSearchParams(window.location.search).get('explain') === 'scores'; } catch { return false; }
}

function ratedKey(sessionId: string): string {
  return `tiles_rated_${sessionId}`;
}

function loadRated(sessionId: string): number[] {
  try { return JSON.parse(readPref(ratedKey(sessionId), '[]')) as number[]; } catch { return []; }
}

/** Step through a recorded game: board before/after each move, why it was chosen, who the players look like. */
export default function Replay({ sessionId }: { sessionId: string }) {
  const [moves, setMoves] = useState<MoveResponse[]>([]);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [view, setView] = useState<'before' | 'after'>('before');
  const [style, setStyle] = usePref('tiles_explain_style', 'full');
  const [rated, setRated] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const scoresOnly = urlScoresOnly() || style === 'scores';

  useEffect(() => {
    setMoves([]); setIdx(0); setPlaying(false); setError(null); setRated(loadRated(sessionId));
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

  const rateable = useMemo(() => moves.filter((x) => x.explanation?.rationale).map((x) => x.step_id), [moves]);

  if (error) return <div className="text-red-400 text-sm" role="alert">{error}</div>;
  if (moves.length === 0) {
    return (
      <div className="text-gray-500 text-sm max-w-md" data-testid="replay-empty">
        No recorded moves with board snapshots for this session yet. Replays appear once the game has made at least one move.
      </div>
    );
  }

  const m = moves[idx];
  const next = moves[idx + 1];
  const go = (n: number) => setIdx(Math.max(0, Math.min(moves.length - 1, n)));
  const btn = 'px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded text-sm disabled:opacity-40';
  const afterBoard = next?.board;                     // the next move's "before" board is this move's result
  const showAfter = view === 'after' && !!afterBoard;
  const alreadyRated = rated.includes(m.step_id);
  const nextUnrated = rateable.find((s) => !rated.includes(s));

  function onKey(e: React.KeyboardEvent) {
    const el = e.target as HTMLElement;
    const typing = el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || (el.tagName === 'INPUT' && (el as HTMLInputElement).type !== 'range');
    if (typing) return;
    if (e.key === 'ArrowRight') { go(idx + 1); e.preventDefault(); }
    else if (e.key === 'ArrowLeft') { go(idx - 1); e.preventDefault(); }
    else if (e.key === ' ' && el.tagName !== 'BUTTON') { setPlaying((p) => !p); e.preventDefault(); }
  }

  return (
    <div className="space-y-4 max-w-6xl mx-auto" data-testid="replay" onKeyDown={onKey}>
      <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Replay controls">
        <button className={btn} onClick={() => go(0)} disabled={idx === 0} title="Jump to start">&#9198;</button>
        <button className={btn} onClick={() => go(idx - 1)} disabled={idx === 0}>&#9664; Prev</button>
        <button className={`${btn} bg-teal-700 hover:bg-teal-600`} onClick={() => setPlaying(!playing)}>
          {playing ? '⏸ Pause' : '▶ Play'}
        </button>
        <button className={btn} onClick={() => go(idx + 1)} disabled={idx >= moves.length - 1}>Next &#9654;</button>
        <button className={btn} onClick={() => go(moves.length - 1)} disabled={idx >= moves.length - 1} title="Jump to end">&#9197;</button>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Playback speed"
                className="bg-gray-800 text-xs rounded px-2 py-1.5 border border-gray-700">
          {SPEEDS.map((s) => <option key={s} value={s}>{s}x</option>)}
        </select>
        <select value={roundStarts.filter((s) => s <= idx).length - 1} aria-label="Jump to round"
                onChange={(e) => go(roundStarts[Number(e.target.value)])}
                className="bg-gray-800 text-xs rounded px-2 py-1.5 border border-gray-700">
          {roundStarts.map((_, r) => <option key={r} value={r}>Round {r + 1}</option>)}
        </select>
        <span className="text-xs text-gray-500 ml-auto">Move {idx + 1} / {moves.length}
          <span className="hidden sm:inline"> &middot; arrow keys step, space plays</span></span>
      </div>

      <input type="range" min={0} max={moves.length - 1} value={idx} onChange={(e) => go(Number(e.target.value))}
             className="w-full accent-teal-500" aria-label="Jump to move" />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        {/* Board */}
        <div className="space-y-3 min-w-0">
          <div className="text-sm">
            <span className="font-semibold text-teal-300">{m.player_name}</span>
            <span className="text-gray-500"> ({m.system_tag || 'unknown model'})</span>
            {m.commentary && !scoresOnly && <span className="text-gray-400"> &mdash; {m.commentary}</span>}
          </div>
          <div className="flex items-center gap-1 text-xs" role="group" aria-label="Board view">
            <button onClick={() => setView('before')} aria-pressed={view === 'before'}
                    className={`px-2 py-1 rounded ${view === 'before' ? 'bg-teal-700' : 'bg-gray-800 hover:bg-gray-700'}`}>Before the move</button>
            <button onClick={() => setView('after')} aria-pressed={view === 'after'} disabled={!afterBoard}
                    title={afterBoard ? 'Show the board once this move has been played' : 'No later board recorded for the last move'}
                    className={`px-2 py-1 rounded disabled:opacity-40 ${view === 'after' ? 'bg-teal-700' : 'bg-gray-800 hover:bg-gray-700'}`}>After the move</button>
          </div>
          <BoardSnapshot
            board={showAfter ? afterBoard! : m.board!}
            action={m.action}
            activePlayer={m.player_name}
            heading={showAfter ? 'Board state after this move' : 'Board state before this move'}
            showMove={!showAfter}
          />
        </div>

        {/* Explanation, profile, rating */}
        <aside className="space-y-3 lg:sticky lg:top-2 self-start" aria-label="Why this move">
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-[10px] text-gray-500">Why this move</div>
              <label className="text-[10px] text-gray-500 flex items-center gap-1">
                Explanation
                <select value={scoresOnly ? 'scores' : 'full'} disabled={urlScoresOnly()}
                        onChange={(e) => setStyle(e.target.value)} aria-label="Explanation style"
                        className="bg-gray-800 text-[10px] rounded px-1 py-0.5 border border-gray-700">
                  <option value="full">Full</option>
                  <option value="scores">Scores only</option>
                </select>
              </label>
            </div>
            {m.explanation?.rationale ? (
              scoresOnly ? (
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
                <>
                  <p className="text-sm text-gray-200 leading-relaxed">{m.explanation.rationale}</p>
                  <div className="text-[10px] text-gray-500">Options considered<Help text={GLOSSARY.alternatives} /></div>
                  <AlternativesChart alternatives={m.explanation.top_alternatives} chosen={m.action} />
                </>
              )
            ) : (
              <p className="text-xs text-gray-500">
                {m.system_tag === 'human'
                  ? 'This move was made by a human, so there is no bot reasoning to show. It was inferred from the board.'
                  : 'No explanation was recorded for this move.'}
              </p>
            )}
          </div>

          <ProfilerInsights sessionId={sessionId} uptoStep={m.step_id} title={`Profile after move ${idx + 1}`} />

          {m.explanation?.rationale && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-3">
              <FeedbackWidget
                key={m.step_id}
                sessionId={sessionId} stepId={m.step_id} alreadyRated={alreadyRated}
                onSaved={() => {
                  const updated = [...new Set([...rated, m.step_id])];
                  setRated(updated);
                  try { window.localStorage.setItem(ratedKey(sessionId), JSON.stringify(updated)); } catch { /* storage unavailable */ }
                }}
              />
              <div className="flex items-center justify-between pt-2 text-[11px] text-gray-500">
                <span data-testid="rated-progress">Rated {rated.filter((s) => rateable.includes(s)).length} of {rateable.length} explained moves</span>
                {nextUnrated !== undefined && (
                  <button className="text-teal-400 hover:text-teal-300 underline"
                          onClick={() => go(moves.findIndex((x) => x.step_id === nextUnrated))}>Next unrated</button>
                )}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
