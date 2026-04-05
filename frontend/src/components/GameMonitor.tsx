import { useEffect, useRef, useState } from 'react';
import { api, connectSessionWs, type GameStateData, type MoveResponse, type SysLogEntry, type Session } from '../api/client';
import { useGameStore } from '../stores/gameStore';
import PlayerBoard, { FactoryDisplay, CenterPoolDisplay } from './PlayerBoard';

function formatDuration(start: string, end: string): string {
  const sec = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  return min < 60 ? `${min}m ${sec % 60}s` : `${Math.floor(min / 60)}h ${min % 60}m`;
}

const TILE_DOTS: Record<string, string> = {
  blue: 'bg-[#67c0dd]',
  yellow: 'bg-[#ffff59]',
  red: 'bg-[#f08080]',
  black: 'bg-[#90ee90]',
  white: 'bg-white',
};

const LOG_LEVEL_COLORS: Record<string, string> = {
  info: 'text-gray-400',
  warning: 'text-yellow-400',
  error: 'text-red-400',
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

function Tile({ color, highlight, ring }: { color?: string | null; highlight?: boolean; ring?: string }) {
  if (!color || color === 'firstPlayer') {
    return <div className={`${TS} rounded bg-gray-800 border border-gray-700`} />;
  }
  return (
    <div
      className={`${TS} rounded ${TILE_DOTS[color] || 'bg-gray-500'} ${
        highlight ? 'ring-2 ring-red-400 scale-110 z-10' : ''
      } ${ring || ''}`}
      title={color}
    />
  );
}

function BoardSnapshot({ board, action, activePlayer }: {
  board: NonNullable<MoveResponse['board']>;
  action: MoveResponse['action'];
  activePlayer: string;
}) {
  const srcFactory = action.source_type === 'factory' ? action.source_index : null;
  const srcCenter = action.source_type === 'center';
  const dstRow = action.destination === 'pattern_line' ? action.destination_row : null;
  const dstFloor = action.destination === 'floor';
  const pickedColor = action.color;

  return (
    <div className="bg-gray-800/60 rounded-xl p-4 space-y-4 border border-gray-700/50">
      <div className="text-xs text-gray-500">Board state before this move</div>

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
                <span className="text-[9px] text-gray-600">empty</span>
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
      {board.players.map((p) => {
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
                  <span className="text-[10px] px-1.5 py-0.5 bg-teal-700 text-teal-200 rounded-full">
                    making this move
                  </span>
                )}
              </div>
              <span className="text-lg font-bold text-teal-400">{p.score}</span>
            </div>

            <div className="flex gap-6 justify-center">
              {/* Pattern Lines (pyramid — right-aligned, filled from right) */}
              <div className="space-y-1">
                <div className="text-[10px] text-gray-500 text-center mb-1">Pattern Lines</div>
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
                        const tile = row[i];
                        return (
                          <div key={`t${i}`} className={`${TS} rounded ${
                            TILE_DOTS[tile] || 'bg-gray-500'
                          } ${isTargetRow ? 'ring-1 ring-yellow-400' : ''}`} />
                        );
                      })}
                    </div>
                  );
                })}
              </div>

              {/* Wall (5x5 grid) */}
              <div className="space-y-1">
                <div className="text-[10px] text-gray-500 text-center mb-1">Wall</div>
                {WALL_PATTERN.map((wallRow, ri) => (
                  <div key={ri} className="flex gap-0.5">
                    {wallRow.map((wc, ci) => (
                      <div
                        key={ci}
                        className={`${TS} rounded ${
                          p.wall[ri]?.[ci]
                            ? `${TILE_DOTS[wc] || 'bg-gray-500'} border border-white/30 shadow-sm`
                            : `${TILE_GHOST[wc] || 'bg-gray-800/30 border border-gray-700/30'}`
                        }`}
                        title={`${wc}${p.wall[ri]?.[ci] ? ' (placed)' : ' (empty)'}`}
                      />
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
                  <div className={`${TS} rounded ${
                    p.floor_line[i]
                      ? `${TILE_DOTS[p.floor_line[i]] || 'bg-gray-500'} ${
                          isActive && dstFloor ? 'ring-1 ring-yellow-400' : ''
                        }`
                      : 'bg-gray-900 border border-gray-700'
                  }`} />
                  <div className="text-[9px] text-red-400/70 mt-0.5">{penalty}</div>
                </div>
              ))}
            </div>
          </div>
        );
      })}

      {/* Move arrow annotation */}
      <div className="flex items-center justify-center gap-2 py-1 text-xs">
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
      </div>
    </div>
  );
}

const PLAYER_COLORS = ['text-blue-300', 'text-red-300', 'text-yellow-300', 'text-green-300'];

function MoveRow({ m, isLast, playerIdx }: { m: MoveResponse; isLast: boolean; playerIdx: number }) {
  const [expanded, setExpanded] = useState(false);
  const color = m.action.color;
  const source =
    m.action.source_type === 'factory'
      ? `Factory ${(m.action.source_index ?? 0) + 1}`
      : 'Center';
  const dest =
    m.action.destination === 'pattern_line'
      ? `Row ${(m.action.destination_row ?? 0) + 1}`
      : 'Floor';
  const pColor = PLAYER_COLORS[playerIdx % 4];

  return (
    <div className={`border-b border-gray-800/30 ${isLast ? 'bg-teal-900/10' : ''}`}>
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-gray-800/30 transition"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-[10px] text-gray-600 w-5 text-right font-mono">{m.step_id}</span>
        <span className={`text-gray-500 text-[10px] transition-transform ${expanded ? 'rotate-90' : ''}`}>&#9654;</span>
        <span className={`font-medium text-xs w-16 truncate ${pColor}`}>{m.player_name}</span>

        {/* Visual move flow: [color tile] source --> destination */}
        <div className="flex items-center gap-1 flex-1 min-w-0">
          <span className={`w-3 h-3 rounded-sm shrink-0 ${TILE_DOTS[color] || 'bg-gray-500'}`} title={color} />
          <span className="text-[11px] text-gray-500 bg-gray-800/80 px-1.5 rounded">{source}</span>
          <svg width="20" height="10" className="shrink-0 text-teal-500">
            <line x1="0" y1="5" x2="14" y2="5" stroke="currentColor" strokeWidth="1.5"/>
            <polygon points="14,1 20,5 14,9" fill="currentColor"/>
          </svg>
          <span className="text-[11px] text-gray-300 bg-gray-800/80 px-1.5 rounded">{dest}</span>
        </div>

        {/* Scores after this move */}
        {m.scores && Object.keys(m.scores).length > 0 && (
          <div className="flex gap-1.5 text-[10px]">
            {Object.entries(m.scores).map(([name, score]) => (
              <span key={name} className="text-gray-500">
                {name.slice(0, 3)}:<span className="text-gray-300">{score}</span>
              </span>
            ))}
          </div>
        )}

        {m.total_ms != null && (
          <span className={`text-[10px] px-1 rounded ${
            m.total_ms > 5000 ? 'text-red-400' : m.total_ms > 2000 ? 'text-yellow-400' : 'text-gray-600'
          }`}>{m.total_ms}ms</span>
        )}
      </div>

      {expanded && (
        <div className="px-8 pb-3 text-xs space-y-2">
          {/* Visual move diagram */}
          <div className="bg-gray-800/50 rounded-lg p-3 flex items-center justify-center gap-4">
            {/* Source */}
            <div className="text-center">
              <div className="text-[10px] text-gray-500 mb-1">Source</div>
              <div className="bg-gray-700 rounded-lg p-2 min-w-[60px]">
                <div className="text-xs text-gray-300 font-medium">{source}</div>
                <div className="flex gap-0.5 justify-center mt-1">
                  <span className={`w-4 h-4 rounded-sm ${TILE_DOTS[color] || 'bg-gray-500'} ring-2 ring-teal-400`} />
                </div>
              </div>
            </div>

            {/* Arrow */}
            <div className="flex flex-col items-center">
              <div className="text-[10px] text-gray-500 capitalize">{color}</div>
              <svg width="60" height="20" className="text-teal-400">
                <defs><marker id="ah" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                  <polygon points="0,0 8,3 0,6" fill="currentColor"/>
                </marker></defs>
                <line x1="0" y1="10" x2="52" y2="10" stroke="currentColor" strokeWidth="2" markerEnd="url(#ah)"/>
              </svg>
              <div className="text-[10px] text-gray-600">{m.player_name}</div>
            </div>

            {/* Destination */}
            <div className="text-center">
              <div className="text-[10px] text-gray-500 mb-1">Destination</div>
              <div className={`rounded-lg p-2 min-w-[60px] ${
                m.action.destination === 'floor' ? 'bg-red-900/30 border border-red-800/50' : 'bg-gray-700'
              }`}>
                <div className="text-xs text-gray-300 font-medium">{dest}</div>
                <div className="flex gap-0.5 justify-center mt-1">
                  <span className={`w-4 h-4 rounded-sm ${TILE_DOTS[color] || 'bg-gray-500'}`} />
                </div>
              </div>
            </div>
          </div>

          {/* Details grid */}
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-gray-800/50 rounded p-2 text-center">
              <div className="text-[10px] text-gray-500">Model</div>
              <div className="text-gray-200 text-[11px]">{m.system_tag || '-'}</div>
            </div>
            {m.legal_actions != null && (
              <div className="bg-gray-800/50 rounded p-2 text-center">
                <div className="text-[10px] text-gray-500">Options</div>
                <div className="text-gray-200 text-[11px]">{m.legal_actions} legal</div>
              </div>
            )}
            <div className="bg-gray-800/50 rounded p-2 text-center">
              <div className="text-[10px] text-gray-500">Time</div>
              <div className="text-gray-200 text-[11px]">{m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : '-'}</div>
            </div>
          </div>

          {/* Timing breakdown */}
          {(m.decision_time_ms != null || m.click_ms != null) && (
            <div className="flex gap-2">
              {m.decision_time_ms != null && (
                <div className="bg-blue-900/20 border border-blue-800/30 rounded px-2 py-1 text-center flex-1">
                  <div className="text-[10px] text-blue-400">ML Decide</div>
                  <div className="text-blue-300 font-mono text-xs">{m.decision_time_ms}ms</div>
                </div>
              )}
              {m.click_ms != null && (
                <div className="bg-green-900/20 border border-green-800/30 rounded px-2 py-1 text-center flex-1">
                  <div className="text-[10px] text-green-400">Execute</div>
                  <div className="text-green-300 font-mono text-xs">{m.click_ms}ms</div>
                </div>
              )}
              {m.ws_wait_ms != null && (
                <div className="bg-yellow-900/20 border border-yellow-800/30 rounded px-2 py-1 text-center flex-1">
                  <div className="text-[10px] text-yellow-400">Confirm</div>
                  <div className="text-yellow-300 font-mono text-xs">{m.ws_wait_ms}ms</div>
                </div>
              )}
              {m.total_ms != null && (
                <div className="bg-teal-900/20 border border-teal-800/30 rounded px-2 py-1 text-center flex-1">
                  <div className="text-[10px] text-teal-400">Total</div>
                  <div className="text-teal-300 font-mono text-xs">{m.total_ms}ms</div>
                </div>
              )}
            </div>
          )}

          {/* Scores after this move */}
          {m.scores && Object.keys(m.scores).length > 0 && (
            <div className="bg-gray-800/50 rounded p-2">
              <div className="text-[10px] text-gray-500 mb-1">Scores after this move</div>
              <div className="flex gap-4">
                {Object.entries(m.scores).map(([name, score]) => (
                  <div key={name} className="text-xs">
                    <span className="text-gray-400">{name}: </span>
                    <span className="text-teal-300 font-bold">{score}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Full board state — game-platform style visualization */}
          {m.board ? (
            <BoardSnapshot board={m.board} action={m.action} activePlayer={m.player_name} />
          ) : (
            <div className="bg-gray-800/30 rounded-lg p-3 text-center text-xs text-gray-600">
              Board snapshot not available for this move (only available during live play)
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface RoundData {
  round: number;
  moves: MoveResponse[];
  endScores?: Record<string, number>;
  scoreChanges?: Record<string, number>; // points gained this round
}

function groupByRound(moves: MoveResponse[]): RoundData[] {
  // Detect round boundaries from board data:
  // A round ends when factories + center become empty (all tiles taken).
  // The NEXT move after that starts a new round (factories refilled).
  const groups: RoundData[] = [];
  let currentRound = 1;
  let currentMoves: MoveResponse[] = [];
  let prevTotalTiles = -1;
  let prevScores: Record<string, number> = {};

  for (let i = 0; i < moves.length; i++) {
    const m = moves[i];

    // Calculate total tiles from board snapshot
    let totalTiles = -1;
    if (m.board) {
      const factoryTiles = m.board.factories.reduce((s, f) => s + f.length, 0);
      const centerTiles = m.board.center_pool.filter(t => t !== 'firstPlayer').length;
      totalTiles = factoryTiles + centerTiles;
    }

    // Detect round boundary: previous move had very few tiles, this move has many (refilled)
    if (prevTotalTiles >= 0 && totalTiles > prevTotalTiles + 5 && currentMoves.length > 0) {
      // Round ended — the previous move was the last in the round
      const lastMove = currentMoves[currentMoves.length - 1];
      const endScores = lastMove.scores || {};
      const scoreChanges: Record<string, number> = {};
      for (const [name, score] of Object.entries(endScores)) {
        scoreChanges[name] = score - (prevScores[name] || 0);
      }
      groups.push({ round: currentRound, moves: currentMoves, endScores, scoreChanges });
      prevScores = { ...endScores };
      currentMoves = [];
      currentRound++;
    }

    currentMoves.push(m);
    if (totalTiles >= 0) prevTotalTiles = totalTiles;
  }

  // Last group
  if (currentMoves.length > 0) {
    const lastMove = currentMoves[currentMoves.length - 1];
    const endScores = lastMove.scores || {};
    const scoreChanges: Record<string, number> = {};
    for (const [name, score] of Object.entries(endScores)) {
      scoreChanges[name] = score - (prevScores[name] || 0);
    }
    groups.push({ round: currentRound, moves: currentMoves, endScores, scoreChanges });
  }

  return groups;
}

function RoundGroup({ round, moves: roundMoves, endScores, scoreChanges }: RoundData) {
  const [collapsed, setCollapsed] = useState(false);
  const playerNames = [...new Set(roundMoves.map((m) => m.player_name))];

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden mb-2">
      {/* Round header */}
      <div
        className="bg-gray-800/50 px-4 py-3 cursor-pointer hover:bg-gray-800/70 transition"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={`text-gray-500 text-xs transition-transform ${collapsed ? '' : 'rotate-90'}`}>&#9654;</span>
            <span className="text-sm font-semibold text-teal-400">Round {round}</span>
            <span className="text-xs text-gray-500">{roundMoves.length} moves</span>
          </div>
          {/* Score summary — change on top, accumulated below */}
          {endScores && Object.keys(endScores).length > 0 && (
            <div className="flex gap-5">
              {Object.entries(endScores).map(([name, score]) => {
                const gained = scoreChanges?.[name] || 0;
                return (
                  <div key={name} className="text-center min-w-[48px]">
                    <div className="text-[10px] text-gray-500 truncate">{name}</div>
                    {gained !== 0 && (
                      <div className={`text-[11px] font-medium ${gained > 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {gained > 0 ? '+' : ''}{gained}
                      </div>
                    )}
                    <div className="text-teal-300 font-bold text-sm">{score}</div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Moves */}
      {!collapsed && (
        <div>
          {roundMoves.map((m, i) => (
            <MoveRow
              key={m.step_id}
              m={m}
              isLast={i === roundMoves.length - 1}
              playerIdx={playerNames.indexOf(m.player_name)}
            />
          ))}
          {/* Round end summary */}
          {endScores && Object.keys(endScores).length > 0 && (
            <div className="bg-gray-800/30 border-t border-gray-700 px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">End of Round {round}</span>
                <div className="flex gap-6">
                  {Object.entries(endScores).map(([name, score]) => {
                    const gained = scoreChanges?.[name] || 0;
                    return (
                      <div key={name} className="text-center min-w-[56px]">
                        <div className="text-[10px] text-gray-500">{name}</div>
                        {gained !== 0 && (
                          <div className={`text-xs font-medium ${gained > 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {gained > 0 ? '+' : ''}{gained}
                          </div>
                        )}
                        <div className="text-teal-300 font-bold text-lg">{score}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function GameMonitor({ sessionId, session: externalSession }: {
  sessionId: string;
  session: Session | null;
}) {
  const {
    currentSession, setCurrentSession,
    gameState, setGameState,
    moves, addMove, setMoves, clearMoves,
    sysLogs, addSysLog, clearSysLogs,
    isConnected, setConnected,
    setError,
  } = useGameStore();

  const wsRef = useRef<WebSocket | null>(null);
  const moveLogRef = useRef<HTMLDivElement>(null);
  const sysLogRef = useRef<HTMLDivElement>(null);
  const [showSysLog, setShowSysLog] = useState(true);
  const [sysLogFilter, setSysLogFilter] = useState<string>('all');

  useEffect(() => {
    setCurrentSession(externalSession);
  }, [externalSession]);

  useEffect(() => {
    if (!sessionId) return;
    setGameState(null);
    clearMoves();
    clearSysLogs();
    setConnected(false);

    api.sessions.get(sessionId).then(setCurrentSession).catch((e) => setError(e.message));
    api.history.get(sessionId).then((data) => setMoves(data.moves)).catch(() => {});

    const ws = connectSessionWs(
      sessionId,
      (msg) => {
        if (msg.type === 'state_update') {
          setGameState(msg.data as GameStateData);
        } else if (msg.type === 'move') {
          addMove(msg.data as MoveResponse);
        } else if (msg.type === 'syslog') {
          addSysLog(msg.data as SysLogEntry);
        } else if (msg.type === 'game_over') {
          addSysLog({
            ts: new Date().toISOString(),
            level: 'info',
            player: 'system',
            phase: 'game_over',
            msg: `Game over! Scores: ${JSON.stringify((msg.data as Record<string, unknown>).scores)}`,
          });
        }
      },
      () => setConnected(false)
    );
    ws.onopen = () => setConnected(true);
    wsRef.current = ws;

    return () => { ws.close(); wsRef.current = null; };
  }, [sessionId]);

  useEffect(() => {
    if (moveLogRef.current) moveLogRef.current.scrollTop = moveLogRef.current.scrollHeight;
  }, [moves]);

  useEffect(() => {
    if (sysLogRef.current) sysLogRef.current.scrollTop = sysLogRef.current.scrollHeight;
  }, [sysLogs]);

  useEffect(() => {
    if (!sessionId) return;
    const interval = setInterval(async () => {
      try { setCurrentSession(await api.sessions.get(sessionId)); } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [sessionId]);

  const status = currentSession?.status || externalSession?.status || 'loading';
  const filteredLogs = sysLogFilter === 'all'
    ? sysLogs
    : sysLogs.filter((l) => l.level === sysLogFilter || l.player === sysLogFilter);

  return (
    <div className="space-y-6">
      {/* Game result banner */}
      {(status === 'completed' || status === 'aborted') && externalSession?.final_scores && (
        <div className={`rounded-xl p-4 mb-2 ${
          status === 'completed' ? 'bg-gradient-to-r from-teal-900/40 to-blue-900/40 border border-teal-700/50'
          : 'bg-gray-800/50 border border-red-800/50'
        }`}>
          <div className="flex items-center justify-between">
            <div>
              {externalSession.winner && status === 'completed' && (
                <div className="text-lg font-bold text-yellow-300 mb-1">
                  {externalSession.winner} wins!
                </div>
              )}
              {status === 'aborted' && (
                <div className="text-sm font-medium text-red-400 mb-1">Game Aborted</div>
              )}
              <div className="text-xs text-gray-400">
                {moves.length} moves &middot; {externalSession.completed_at
                  ? formatDuration(externalSession.created_at, externalSession.completed_at)
                  : ''}
              </div>
            </div>
            <div className="flex gap-6">
              {Object.entries(externalSession.final_scores)
                .sort(([,a], [,b]) => (b as number) - (a as number))
                .map(([name, score]) => (
                  <div key={name} className="text-center">
                    <div className={`text-xs ${name === externalSession.winner ? 'text-yellow-300 font-medium' : 'text-gray-400'}`}>
                      {name} {name === externalSession.winner ? '👑' : ''}
                    </div>
                    <div className={`text-2xl font-bold ${name === externalSession.winner ? 'text-yellow-300' : 'text-gray-300'}`}>
                      {score as number}
                    </div>
                  </div>
                ))}
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <span className={`text-xs px-2 py-0.5 rounded-full ${
            status === 'playing' ? 'bg-green-700 text-green-200'
              : status === 'completed' ? 'bg-blue-700 text-blue-200'
              : status === 'aborted' ? 'bg-red-700 text-red-200'
              : 'bg-gray-700 text-gray-300'
          }`}>{status}</span>
          <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`}
                title={isConnected ? 'WS connected' : 'Disconnected'} />
          <span className="text-xs text-gray-600">
            {moves.length} moves | {sysLogs.length} logs
          </span>
          {status === 'playing' && (
            <button
              onClick={async () => { try { await api.sessions.stop(sessionId); } catch {} }}
              className="px-3 py-1 bg-red-800 hover:bg-red-700 rounded text-xs transition"
            >
              Stop
            </button>
          )}
          {status === 'created' && (
            <button
              onClick={async () => { try { await api.sessions.start(sessionId); } catch {} }}
              className="px-3 py-1 bg-green-700 hover:bg-green-600 rounded text-xs transition"
            >
              Start
            </button>
          )}
        </div>
        <button
          onClick={async () => {
            try {
              const resp = await fetch(`/api/history/${sessionId}/export`);
              const data = await resp.json();
              const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `oppoprofile_${currentSession?.room_name || sessionId}.json`;
              a.click();
              URL.revokeObjectURL(url);
            } catch (e) { console.error(e); }
          }}
          className="px-3 py-1.5 bg-teal-800 hover:bg-teal-700 rounded-lg text-xs transition"
        >
          Download JSON
        </button>
      </div>

      {!gameState && status === 'playing' && (
        <div className="flex items-center gap-2 text-gray-500 text-xs py-2">
          <div className="animate-spin w-4 h-4 border-2 border-teal-500 border-t-transparent rounded-full" />
          Waiting for game state...
        </div>
      )}

      {gameState && (
        <>
          {/* Round and Turn Info */}
          <div className="flex items-center gap-4 text-sm flex-wrap">
            <span className="bg-gray-800 px-3 py-1 rounded-lg">
              Round <span className="text-teal-400 font-bold">{gameState.round}</span>
            </span>
            <span className="bg-gray-800 px-3 py-1 rounded-lg">
              Turn: <span className="text-yellow-300 font-semibold">{gameState.current_turn}</span>
            </span>
            {gameState.game_over && (
              <span className="bg-blue-800 px-3 py-1 rounded-lg text-blue-200 font-semibold">Game Over</span>
            )}
            {moves.length > 0 && (
              <span className="bg-gray-800 px-3 py-1 rounded-lg text-gray-400">
                Avg: {Math.round(moves.reduce((s, m) => s + (m.total_ms || 0), 0) / moves.length)}ms/move
              </span>
            )}
          </div>

          {/* Factories */}
          <div>
            <h3 className="text-sm text-gray-400 mb-2">Factories ({gameState.factories.length})</h3>
            <div className="flex flex-wrap gap-3">
              {gameState.factories.map((factory, i) => (
                <FactoryDisplay key={i} tiles={factory} index={i} />
              ))}
            </div>
          </div>

          {/* Center Pool */}
          {gameState.center_pool.length > 0 && (
            <div>
              <h3 className="text-sm text-gray-400 mb-2">Center Pool</h3>
              <CenterPoolDisplay tiles={gameState.center_pool} />
            </div>
          )}

          {/* Player Boards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {gameState.players.map((player) => (
              <PlayerBoard key={player.index} player={player}
                           isCurrentTurn={player.name === gameState.current_turn} />
            ))}
          </div>
        </>
      )}

      {/* Move Log — grouped by round */}
      <div>
        <h3 className="text-sm text-gray-400 mb-2">Move Log ({moves.length} moves)</h3>
        <div ref={moveLogRef}
             className="max-h-[500px] overflow-y-auto space-y-0">
          {moves.length === 0 ? (
            <div className="bg-gray-900 border border-gray-800 rounded-lg text-gray-600 text-sm p-4 text-center">
              No moves recorded yet.
            </div>
          ) : (
            groupByRound(moves).map((group) => (
              <RoundGroup
                key={group.round}
                {...group}
              />
            ))
          )}
        </div>
      </div>

      {/* System Log */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm text-gray-400">
            System Log ({sysLogs.length})
          </h3>
          <div className="flex items-center gap-2">
            <select
              value={sysLogFilter}
              onChange={(e) => setSysLogFilter(e.target.value)}
              className="bg-gray-800 text-gray-300 text-xs rounded px-2 py-1 border border-gray-700"
            >
              <option value="all">All</option>
              <option value="error">Errors only</option>
              <option value="warning">Warnings</option>
              {gameState?.players.map((p) => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>
            <button
              onClick={() => setShowSysLog(!showSysLog)}
              className="text-xs text-gray-500 hover:text-gray-300"
            >
              {showSysLog ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>
        {showSysLog && (
          <div ref={sysLogRef}
               className="bg-gray-950 border border-gray-800 rounded-lg max-h-48 overflow-y-auto font-mono text-xs">
            {filteredLogs.length === 0 ? (
              <div className="text-gray-700 p-3 text-center">No system logs yet.</div>
            ) : (
              filteredLogs.map((log, i) => (
                <div key={i} className={`px-3 py-0.5 border-b border-gray-900/50 ${LOG_LEVEL_COLORS[log.level] || 'text-gray-400'}`}>
                  <span className="text-gray-600">{log.ts.split('T')[1]?.slice(0, 12) || ''}</span>
                  {' '}
                  <span className={`${
                    log.level === 'error' ? 'text-red-500' : log.level === 'warning' ? 'text-yellow-500' : 'text-gray-600'
                  }`}>
                    [{log.level.toUpperCase().padEnd(5)}]
                  </span>
                  {' '}
                  <span className="text-teal-400">[{log.player}]</span>
                  {' '}
                  <span className="text-gray-500">[{log.phase}]</span>
                  {' '}
                  {log.msg}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
