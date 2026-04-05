import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api/client';
import SessionConfig from './components/SessionConfig';
import GameMonitor from './components/GameMonitor';
import ProfileAnalyzer from './components/ProfileAnalyzer';
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
  const [activeTab, setActiveTab] = useState<'config' | 'monitor' | 'profile'>('config');
  const [sidebarWidth, setSidebarWidth] = useState(240);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
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
  const sw = sidebarCollapsed ? 0 : sidebarWidth;

  return (
    <div className="h-screen flex flex-col bg-gray-950 text-gray-100">
      {/* Top bar */}
      <nav className="bg-gray-900 border-b border-gray-700 px-3 py-1.5 flex items-center gap-1 shrink-0">
        <span className="text-lg font-bold text-teal-400 tracking-tight mr-3">OppoProfile</span>

        <button
          onClick={() => setActiveTab('config')}
          className={`px-3 py-1.5 rounded text-sm font-medium transition ${
            activeTab === 'config' ? 'bg-gray-800 text-teal-400' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Session Configuration
        </button>
        {selectedId && selected && (
          <>
            <button
              onClick={() => setActiveTab('monitor')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition ${
                activeTab === 'monitor' ? 'bg-gray-800 text-teal-400' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Game Monitor
            </button>
            <button
              onClick={() => setActiveTab('profile')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition ${
                activeTab === 'profile' ? 'bg-gray-800 text-teal-400' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Profile Analyzing
            </button>
            <span className="text-xs text-gray-600 ml-2">{selected.room_name}</span>
          </>
        )}
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
                Sessions ({sessions.length})
              </div>

              <div className="flex-1 overflow-y-auto">
                {sessions.length === 0 ? (
                  <div className="px-3 py-4 text-xs text-gray-600 text-center">No sessions</div>
                ) : (
                  sessions.map((s) => {
                    const players = s.player_config.map((p) => {
                      const label = p.type === 'human' ? 'H' : p.type === 'GreedyPlayer' ? 'G' : 'R';
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
                        <div className="text-[10px] text-gray-600 mt-0.5 truncate">
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
          ) : activeTab === 'monitor' && selectedId && selected ? (
            <div className="flex-1 overflow-y-auto p-4">
              <GameMonitor sessionId={selectedId} session={selected} />
            </div>
          ) : activeTab === 'profile' && selectedId && selected ? (
            <div className="flex-1 overflow-y-auto p-4">
              <ProfileAnalyzer sessionId={selectedId} session={selected} />
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-600">
              <div className="text-center text-sm">Select a session or create a new one</div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
