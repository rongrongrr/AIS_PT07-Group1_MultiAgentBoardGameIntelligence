import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api/client';
import SessionConfig from './components/SessionConfig';
import GameMonitor from './components/GameMonitor';
import ProfileAnalyzer from './components/ProfileAnalyzer';
import Replay from './components/Replay';
import Leaderboard from './components/Leaderboard';
import { PatternsContext } from './components/BoardSnapshot';
import { useFlag, usePref } from './lib/prefs';
import { useTheme, type ThemePref } from './lib/theme';
import { useGameStore } from './stores/gameStore';

const STATUS_COLORS: Record<string, string> = {
  created: 'bg-gray-600',
  lobby: 'bg-yellow-600',
  playing: 'bg-green-600',
  completed: 'bg-blue-600',
  aborted: 'bg-red-600',
};

function formatDuration(start: string, end: string | null): string {
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const sec = Math.round((e - s) / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

export default function App() {
  const { sessions, setSessions } = useGameStore();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'config' | 'monitor' | 'replay' | 'profile' | 'leaderboard'>('config');
  const [sidebarWidth, setSidebarWidth] = useState(240);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => typeof window !== 'undefined' && window.innerWidth < 768);
  const [patterns, setPatterns] = useFlag('tiles_patterns', false);
  const [theme, setTheme] = useTheme();
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = usePref('tiles_status_filter', 'all');
  const resizing = useRef(false);

  useEffect(() => {
    loadSessions();
    const iv = setInterval(loadSessions, 5000);
    return () => clearInterval(iv);
  }, []);

  async function loadSessions() {
    try { setSessions(await api.sessions.list()); } catch {}
  }

  // Drag-to-resize sidebar
  const onMouseDown = useCallback(() => {
    resizing.current = true;
    const onMove = (e: MouseEvent) => {
      if (!resizing.current) return;
      const w = Math.max(180, Math.min(400, e.clientX));
      setSidebarWidth(w);
      if (w < 100) setSidebarCollapsed(true);
    };
    const onUp = () => {
      resizing.current = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, []);

  const selected = sessions.find((s) => s.id === selectedId) || null;
  const shown = sessions.filter((s) =>
    (statusFilter === 'all' || s.status === statusFilter || (statusFilter === 'running' && ['lobby', 'playing'].includes(s.status))) &&
    (!query.trim() || `${s.room_name} ${s.player_config.map((p) => p.name || p.type).join(' ')} ${s.winner || ''}`.toLowerCase().includes(query.trim().toLowerCase())));
  const sw = sidebarCollapsed ? 0 : sidebarWidth;

  return (
    <PatternsContext.Provider value={patterns}>
    <div className="h-screen flex flex-col bg-gray-950 text-gray-100">
      {/* Top bar */}
      <nav className="bg-gray-900 border-b border-gray-700 px-3 py-1.5 flex items-center gap-1 shrink-0 overflow-x-auto" aria-label="Main" role="tablist">
        <button onClick={() => setSidebarCollapsed(!sidebarCollapsed)} aria-label="Toggle the session list"
                aria-expanded={!sidebarCollapsed} className="md:hidden px-2 py-1 text-gray-400 hover:text-gray-200">&#9776;</button>
        <span className="text-lg font-bold text-teal-400 tracking-tight mr-3">TILES</span>

        <button
          role="tab" aria-selected={activeTab === 'config'}
          onClick={() => setActiveTab('config')}
          className={`px-3 py-1.5 rounded text-sm font-medium transition ${
            activeTab === 'config' ? 'bg-gray-800 text-teal-400' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          New session
        </button>
        <button
          role="tab" aria-selected={activeTab === 'leaderboard'}
          onClick={() => setActiveTab('leaderboard')}
          className={`px-3 py-1.5 rounded text-sm font-medium transition ${
            activeTab === 'leaderboard' ? 'bg-gray-800 text-teal-400' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Leaderboard
        </button>
        {selectedId && selected && (
          <>
            <button
              role="tab" aria-selected={activeTab === 'monitor'}
          onClick={() => setActiveTab('monitor')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition ${
                activeTab === 'monitor' ? 'bg-gray-800 text-teal-400' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Game Monitor
            </button>
            <button
              role="tab" aria-selected={activeTab === 'replay'}
          onClick={() => setActiveTab('replay')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition ${
                activeTab === 'replay' ? 'bg-gray-800 text-teal-400' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Replay
            </button>
            <button
              role="tab" aria-selected={activeTab === 'profile'}
          onClick={() => setActiveTab('profile')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition ${
                activeTab === 'profile' ? 'bg-gray-800 text-teal-400' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Player profiles
            </button>
            <span className="text-xs text-gray-500 ml-2 whitespace-nowrap">{selected.room_name}</span>
          </>
        )}
        <label className="ml-auto flex items-center gap-1.5 text-xs text-gray-400 whitespace-nowrap">
          Theme
          <select value={theme} onChange={(e) => setTheme(e.target.value as ThemePref)} aria-label="Colour theme"
                  className="bg-gray-800 text-xs rounded px-1.5 py-1 border border-gray-700">
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="system">Match system</option>
          </select>
        </label>
        <label className="ml-3 flex items-center gap-1.5 text-xs text-gray-400 whitespace-nowrap cursor-pointer"
               title="Adds a letter to every tile (B, Y, R, G, W) so colours are not the only cue">
          <input type="checkbox" checked={patterns} onChange={(e) => setPatterns(e.target.checked)} className="accent-teal-500" />
          Tile letters
        </label>
      </nav>

      <div className="flex flex-1 overflow-hidden relative">
        {/* Left sidebar */}
        <aside
          className="bg-gray-900 border-r border-gray-800 flex flex-col shrink-0 transition-all duration-150"
          style={{ width: `${sw}px`, minWidth: sidebarCollapsed ? 0 : undefined }}
        >
          {!sidebarCollapsed && (
            <>
              {/* + Session button */}
              <button
                onClick={() => { setActiveTab('config'); setSelectedId(null); }}
                className="mx-2 mt-2 mb-1 px-3 py-2 bg-teal-700 hover:bg-teal-600 rounded-lg text-sm font-medium transition text-center"
              >
                + Session
              </button>

              <div className="px-3 py-1.5 text-[10px] text-gray-500 font-medium uppercase tracking-wider border-b border-gray-800">
                Sessions ({shown.length}{shown.length !== sessions.length ? ` of ${sessions.length}` : ''})
              </div>
              <div className="px-2 py-1.5 space-y-1.5 border-b border-gray-800">
                <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search room, player, winner"
                       aria-label="Search sessions"
                       className="w-full bg-gray-800 text-xs rounded px-2 py-1 border border-gray-700 focus:border-teal-500 focus:outline-none" />
                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter sessions by status"
                        className="w-full bg-gray-800 text-xs rounded px-2 py-1 border border-gray-700">
                  <option value="all">All statuses</option>
                  <option value="running">Running</option>
                  <option value="completed">Completed</option>
                  <option value="aborted">Aborted</option>
                  <option value="created">Not started</option>
                </select>
              </div>

              <div className="flex-1 overflow-y-auto">
                {shown.length === 0 ? (
                  <div className="px-3 py-4 text-xs text-gray-500 text-center">
                    {sessions.length === 0 ? 'No sessions yet. Create one to get started.' : 'No sessions match the search or filter.'}
                  </div>
                ) : (
                  shown.map((s) => {
                    const players = s.player_config.map((p) => {
                      const label = p.type === 'human' ? 'H' : p.type.charAt(0);
                      return `${label}:${p.name || p.type}`;
                    });
                    const duration = formatDuration(s.created_at, s.completed_at);

                    return (
                      <button
                        key={s.id}
                        onClick={() => { setSelectedId(s.id); setActiveTab('monitor'); }}
                        className={`w-full text-left px-3 py-2.5 border-b border-gray-800/50 transition ${
                          selectedId === s.id
                            ? 'bg-gray-800 border-l-2 border-l-teal-400'
                            : 'hover:bg-gray-800/50 border-l-2 border-l-transparent'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium truncate flex-1">{s.room_name}</span>
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                            s.status === 'playing' ? 'bg-green-400 animate-pulse'
                            : s.status === 'completed' ? 'bg-blue-400'
                            : s.status === 'aborted' ? 'bg-red-400'
                            : 'bg-gray-500'
                          }`} />
                        </div>
                        <div className="text-[10px] text-gray-500 mt-0.5 flex items-center gap-1 flex-wrap">
                          <span className={`px-1 rounded text-[9px] ${STATUS_COLORS[s.status] || 'bg-gray-600'} text-white`}>
                            {s.status}
                          </span>
                          <span>{duration}</span>
                          {s.winner && (
                            <span className="text-yellow-400 font-medium">
                              {s.winner} wins
                            </span>
                          )}
                        </div>
                        {s.final_scores && (
                          <div className="text-[10px] text-gray-500 mt-0.5 flex gap-2">
                            {Object.entries(s.final_scores)
                              .sort(([,a], [,b]) => b - a)
                              .map(([name, score]) => (
                                <span key={name} className={name === s.winner ? 'text-yellow-300 font-medium' : ''}>
                                  {name}:{score}
                                </span>
                              ))}
                          </div>
                        )}
                        <div className="text-[10px] text-gray-500 mt-0.5 truncate">
                          {players.join(', ')}
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
            </>
          )}
        </aside>

        {/* Resize handle */}
        <div
          className="w-1 cursor-col-resize hover:bg-teal-500/30 active:bg-teal-500/50 shrink-0 relative group"
          onMouseDown={onMouseDown}
          onDoubleClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          title="Drag to resize, double-click to collapse"
        >
          <div className="absolute inset-y-0 -left-1 -right-1" />
        </div>

        {/* Main pane */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {activeTab === 'config' ? (
            <div className="flex-1 overflow-y-auto p-6 max-w-4xl mx-auto w-full">
              <SessionConfig onCreated={(id) => {
                setSelectedId(id);
                setActiveTab('monitor');
                loadSessions();
              }} />
            </div>
          ) : activeTab === 'leaderboard' ? (
            <div className="flex-1 overflow-y-auto p-6 max-w-4xl mx-auto w-full">
              <Leaderboard />
            </div>
          ) : activeTab === 'monitor' && selectedId && selected ? (
            <div className="flex-1 overflow-y-auto p-4">
              <GameMonitor sessionId={selectedId} session={selected} />
            </div>
          ) : activeTab === 'replay' && selectedId && selected ? (
            <div className="flex-1 overflow-y-auto p-4">
              <Replay sessionId={selectedId} />
            </div>
          ) : activeTab === 'profile' && selectedId && selected ? (
            <div className="flex-1 overflow-y-auto p-4">
              <ProfileAnalyzer sessionId={selectedId} session={selected} />
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-500 p-6">
              <div className="text-center text-sm space-y-2 max-w-sm">
                <div>Select a session from the list, or create a new one.</div>
                <button onClick={() => { setActiveTab('config'); setSelectedId(null); }}
                        className="px-4 py-2 bg-teal-700 hover:bg-teal-600 rounded-lg text-gray-100">New session</button>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
    </PatternsContext.Provider>
  );
}
