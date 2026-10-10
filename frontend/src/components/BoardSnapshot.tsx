import { createContext, useContext } from 'react';
import type { MoveResponse } from '../api/client';

/** When true every coloured tile also shows a letter, for colour-blind players. */
export const PatternsContext = createContext(false);
const LETTERS: Record<string, string> = { blue: 'B', yellow: 'Y', red: 'R', black: 'G', white: 'W' };


export const TILE_DOTS: Record<string, string> = {
  blue: 'bg-[#67c0dd]',
  yellow: 'bg-[#ffff59]',
  red: 'bg-[#f08080]',
  black: 'bg-[#90ee90]',
  white: 'bg-white',
};

const WALL_PATTERN = [
  ['blue', 'yellow', 'red', 'black', 'white'],
  ['white', 'blue', 'yellow', 'red', 'black'],
  ['black', 'white', 'blue', 'yellow', 'red'],
  ['red', 'black', 'white', 'blue', 'yellow'],
  ['yellow', 'red', 'black', 'white', 'blue'],
];

const TILE_GHOST: Record<string, string> = {
  blue: 'bg-[#67c0dd]/20 border border-[#67c0dd]/30',
  yellow: 'bg-[#ffff59]/15 border border-[#ffff59]/25',
  red: 'bg-[#f08080]/20 border border-[#f08080]/30',
  black: 'bg-[#90ee90]/15 border border-[#90ee90]/25',
  white: 'bg-white/10 border border-white/20',
};

const FLOOR_PENALTIES = [-1, -1, -2, -2, -2, -3, -3];
const TS = 'w-5 h-5'; // tile size class

function ColorCell({ color, className = '', title }: { color: string; className?: string; title?: string }) {
  const patterns = useContext(PatternsContext);
  return (
    <div
      className={`${TS} rounded ${TILE_DOTS[color] || 'bg-gray-500'} ${className} ${
        patterns ? 'flex items-center justify-center text-[10px] font-bold text-gray-900' : ''
      }`}
      title={title ?? color}
    >{patterns ? LETTERS[color] ?? '' : null}</div>
  );
}

function Tile({ color, highlight, ring }: { color?: string | null; highlight?: boolean; ring?: string }) {
  if (!color || color === 'firstPlayer') {
    return <div className={`${TS} rounded bg-gray-800 border border-gray-700`} title={color === 'firstPlayer' ? 'first-player token' : 'empty'} />;
  }
  return (
    <ColorCell
      color={color}
      className={`${highlight ? 'ring-2 ring-red-400 scale-110 z-10 tile-pulse' : ''} ${ring || ''}`}
    />
  );
}

export default function BoardSnapshot({ board, action, activePlayer, heading = 'Board state before this move', showMove = true, compact = false }: {
  board: NonNullable<MoveResponse['board']>;
  action: MoveResponse['action'];
  activePlayer: string;
  heading?: string;
  /** false for the "after" view, where the move has already happened and nothing is highlighted */
  showMove?: boolean;
  /** hide the per-player boards (factories and the move arrow only) */
  compact?: boolean;
}) {
  if (!showMove) action = { ...action, source_index: -1, source_type: 'none', destination: 'none', destination_row: -1 };
  const srcFactory = action.source_type === 'factory' ? action.source_index : null;
  const srcCenter = action.source_type === 'center';
  const dstRow = action.destination === 'pattern_line' ? action.destination_row : null;
  const dstFloor = action.destination === 'floor';
  const pickedColor = action.color;

  return (
    <div className="bg-gray-800/60 rounded-xl p-4 space-y-4 border border-gray-700/50">
      <div className="text-xs text-gray-500">{heading}</div>

      {/* Factories row */}
      <div className="flex flex-wrap items-center gap-3 justify-center">
        {board.factories.map((f, fi) => {
          const isSource = srcFactory === fi;
          return (
            <div
              key={fi}
              className={`bg-gray-700 rounded-full w-16 h-16 flex flex-wrap items-center justify-center gap-0.5 p-1 relative ${
                isSource ? 'ring-3 ring-red-400 shadow-lg shadow-red-500/20' : ''
              }`}
            >
              {f.length === 0 ? (
                <span className="text-[10px] text-gray-300">empty</span>
              ) : (
                f.map((t, ti) => (
                  <Tile
                    key={ti}
                    color={t}
                    highlight={isSource && t === pickedColor}
                  />
                ))
              )}
            </div>
          );
        })}
      </div>

      {/* Center pool */}
      {board.center_pool.length > 0 && (
        <div className={`flex flex-wrap gap-1 justify-center py-2 px-4 rounded-lg ${
          srcCenter ? 'bg-red-900/20 ring-2 ring-red-400' : 'bg-gray-800/40'
        }`}>
          {board.center_pool.map((t, i) => (
            <Tile
              key={i}
              color={t}
              highlight={srcCenter && t === pickedColor}
            />
          ))}
        </div>
      )}

      {/* Player boards */}
      {!compact && board.players.map((p) => {
        const isActive = p.name === activePlayer;
        return (
          <div
            key={p.name}
            className={`rounded-xl p-4 ${
              isActive
                ? 'bg-gray-700/60 border-2 border-teal-500/60 shadow-lg shadow-teal-500/10'
                : 'bg-gray-800/40 border border-gray-700/30'
            }`}
          >
            {/* Player header */}
            <div className="flex justify-between items-center mb-3">
              <div className="flex items-center gap-2">
                <span className={`font-bold text-sm ${isActive ? 'text-teal-300' : 'text-gray-300'}`}>
                  {p.name}
                </span>
                {isActive && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-teal-900 text-teal-300 rounded-full">
                    making this move
                  </span>
                )}
              </div>
              <span className="text-lg font-bold text-teal-400">{p.score}</span>
            </div>

            <div className="flex gap-6 justify-center">
              {/* Pattern Lines (pyramid — right-aligned, filled from right) */}
              <div className="space-y-1">
                <div className="text-[10px] text-gray-400 text-center mb-1">Pattern Lines</div>
                {p.pattern_lines.map((row, ri) => {
                  const isTargetRow = isActive && dstRow === ri;
                  const capacity = ri + 1;
                  const filled = row.length;
                  const empty = capacity - filled;
                  return (
                    <div key={ri} className={`flex gap-0.5 justify-end items-center ${
                      isTargetRow ? 'bg-yellow-500/10 rounded px-1 -mx-1' : ''
                    }`}>
                      {isTargetRow && (
                        <span className="text-yellow-400 text-xs mr-1">&#8594;</span>
                      )}
                      {/* Empty slots (left side) */}
                      {Array.from({ length: empty }).map((_, i) => (
                        <div key={`e${i}`} className={`${TS} rounded bg-gray-900 border border-gray-600 ${
                          isTargetRow ? 'ring-1 ring-yellow-400' : ''
                        }`} />
                      ))}
                      {/* Filled tiles (right side, closest to wall) */}
                      {Array.from({ length: filled }).map((_, i) => {
                        return (
                          <ColorCell key={`t${i}`} color={row[i]} className={isTargetRow ? 'ring-1 ring-yellow-400' : ''} />
                        );
                      })}
                    </div>
                  );
                })}
              </div>

              {/* Wall (5x5 grid) */}
              <div className="space-y-1">
                <div className="text-[10px] text-gray-400 text-center mb-1">Wall</div>
                {WALL_PATTERN.map((wallRow, ri) => (
                  <div key={ri} className="flex gap-0.5">
                    {wallRow.map((wc, ci) => (
                      p.wall[ri]?.[ci] ? (
                        <ColorCell key={ci} color={wc} className="border border-white/30 shadow-sm" title={`${wc} (placed)`} />
                      ) : (
                        <div key={ci} className={`${TS} rounded ${TILE_GHOST[wc] || 'bg-gray-800/30 border border-gray-700/30'}`}
                             title={`${wc} (empty)`} />
                      )
                    ))}
                  </div>
                ))}
              </div>
            </div>

            {/* Floor line */}
            <div className="mt-3 flex items-center gap-1 justify-center">
              <span className="text-[10px] text-gray-500 mr-1">Floor:</span>
              {FLOOR_PENALTIES.map((penalty, i) => (
                <div key={i} className="text-center">
                  {p.floor_line[i] ? (
                    <ColorCell color={p.floor_line[i]} className={isActive && dstFloor ? 'ring-1 ring-yellow-400' : ''} />
                  ) : (
                    <div className={`${TS} rounded bg-gray-900 border border-gray-700`} />
                  )}
                  <div className="text-[9px] text-red-400 mt-0.5">{penalty}</div>
                </div>
              ))}
            </div>
          </div>
        );
      })}

      {/* Move arrow annotation */}
      {showMove && <div className="flex items-center justify-center gap-2 py-1 text-xs">
        <span className={`px-2 py-1 rounded ${
          srcFactory !== null ? 'bg-red-900/30 text-red-300 ring-1 ring-red-500/50' : 'bg-red-900/30 text-red-300 ring-1 ring-red-500/50'
        }`}>
          {srcFactory !== null ? `Factory ${srcFactory + 1}` : 'Center'}
        </span>
        <span className="capitalize px-1.5 py-0.5 rounded" style={{
          backgroundColor: `color-mix(in srgb, ${
            pickedColor === 'blue' ? '#67c0dd' : pickedColor === 'red' ? '#f08080'
            : pickedColor === 'yellow' ? '#ffff59' : pickedColor === 'black' ? '#90ee90' : '#ffffff'
          } 30%, transparent)`
        }}>
          {pickedColor}
        </span>
        <svg width="24" height="12" className="text-red-400">
          <line x1="0" y1="6" x2="16" y2="6" stroke="currentColor" strokeWidth="2"/>
          <polygon points="16,2 24,6 16,10" fill="currentColor"/>
        </svg>
        <span className={`px-2 py-1 rounded ${
          dstFloor ? 'bg-red-900/30 text-red-300' : 'bg-yellow-900/30 text-yellow-300 ring-1 ring-yellow-500/50'
        }`}>
          {dstFloor ? 'Floor' : `Row ${(dstRow ?? 0) + 1}`}
        </span>
        <span className="text-gray-500">by {activePlayer}</span>
      </div>}
    </div>
  );
}
