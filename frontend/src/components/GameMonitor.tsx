import { useEffect, useRef, useState } from 'react';
import ProfilerInsights from './ProfilerInsights';
import StatusBanner, { describeStatus } from './StatusBanner';
import { api, connectSessionWs, type GameStateData, type MoveResponse, type SysLogEntry, type Session } from '../api/client';
import { useGameStore } from '../stores/gameStore';
import PlayerBoard, { FactoryDisplay, CenterPoolDisplay } from './PlayerBoard';
import BoardSnapshot, { TILE_DOTS } from './BoardSnapshot';
import FeedbackWidget from './FeedbackWidget';

function formatDuration(start: string, end: string): string {
  const sec = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  return min < 60 ? `${min}m ${sec % 60}s` : `${Math.floor(min / 60)}h ${min % 60}m`;
}

const LOG_LEVEL_COLORS: Record<string, string> = {
  info: 'text-gray-400',
  warning: 'text-yellow-400',
  error: 'text-red-400',
};

const PLAYER_COLORS = ['text-blue-300', 'text-red-300', 'text-yellow-300', 'text-green-300'];

function MoveRow({ m: move, isLast, playerIdx, sessionId }: { m: MoveResponse; isLast: boolean; playerIdx: number; sessionId: string }) {
  const m = { ...move, sessionId };
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

        {/* Scores before this move */}
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

          {/* Why this move: rationale, then the model's top-scoring options */}
          {m.explanation && (
            <div className="bg-gray-800/50 rounded p-2 space-y-1">
              {m.explanation.rationale && (
                <p className="text-[12px] text-gray-200 leading-relaxed">{m.explanation.rationale}</p>
              )}
              {m.commentary && <p className="text-[11px] italic text-gray-500">{m.commentary}</p>}
              <div className="text-[10px] text-gray-500">
                Why this move ({m.explanation.model}, {m.explanation.n_legal} legal options)
              </div>
              {m.explanation.adaptation && (
                <div className="text-[11px] text-yellow-300">
                  Adaptation: {m.explanation.adaptation.reason} (playing as {m.explanation.adaptation.playing_as})
                </div>
              )}
              {m.explanation.top_alternatives.map((alt, i) => (
                <div key={i} className={`text-[11px] flex gap-2 ${i === 0 ? 'text-teal-300' : 'text-gray-400'}`}>
                  <span className="w-10 text-right font-mono">{alt.score.toFixed(1)}</span>
                  <span>
                    {alt.action.color} from {alt.action.source_type === 'factory'
                      ? `factory ${(alt.action.source_index ?? 0) + 1}` : 'center'}
                    {' → '}
                    {alt.action.destination === 'floor' ? 'floor' : `row ${(alt.action.destination_row ?? 0) + 1}`}
                    {i === 0 ? ' (chosen)' : ''}
                  </span>
                </div>
              ))}
              {m.explanation.rationale && m.sessionId && (
                <FeedbackWidget sessionId={m.sessionId} stepId={m.step_id} />
              )}
            </div>
          )}

          {/* Scores before this move */}
          {m.scores && Object.keys(m.scores).length > 0 && (
            <div className="bg-gray-800/50 rounded p-2">
              <div className="text-[10px] text-gray-500 mb-1">Scores before this move</div>
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

function RoundGroup({ round, moves: roundMoves, endScores, scoreChanges, sessionId }: RoundData & { sessionId: string }) {
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
              sessionId={sessionId}
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
  const [actionError, setActionError] = useState<string | null>(null);

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

    let disposed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const open = () => {
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
      () => {
        setConnected(false);
        if (!disposed) retry = setTimeout(open, 2000);   // keep trying: the game runs on regardless
      }
    );
    ws.onopen = () => setConnected(true);
    wsRef.current = ws;
    };
    open();

    return () => { disposed = true; clearTimeout(retry); wsRef.current?.close(); wsRef.current = null; };
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
      <StatusBanner view={describeStatus(currentSession || externalSession, gameState, moves.length, isConnected)} />
      {actionError && (
        <div role="alert" className="bg-red-900/50 border border-red-700 text-red-200 px-4 py-2 rounded-lg text-sm flex justify-between">
          <span>{actionError}</span>
          <button onClick={() => setActionError(null)} className="text-red-400 hover:text-red-200 text-xs">Dismiss</button>
        </div>
      )}

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
              onClick={async () => {
                if (!window.confirm('Stop this session? The browsers close and the game is marked aborted.')) return;
                try { setActionError(null); await api.sessions.stop(sessionId); } catch (e: any) { setActionError(e.message); }
              }}
              className="px-3 py-1 bg-red-800 hover:bg-red-700 rounded text-xs transition"
            >
              Stop
            </button>
          )}
          {status === 'created' && (
            <button
              onClick={async () => { try { setActionError(null); await api.sessions.start(sessionId); } catch (e: any) { setActionError(e.message); } }}
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
              a.download = `tiles_${currentSession?.room_name || sessionId}.json`;
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

      {/* Profiler insights (live) */}
      {moves.length > 0 && <ProfilerInsights sessionId={sessionId} refreshKey={moves.length} />}

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
                sessionId={sessionId}
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
