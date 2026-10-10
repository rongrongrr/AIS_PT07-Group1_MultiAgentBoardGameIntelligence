import { useEffect, useState } from 'react';
import { api, type PlayerSlotConfig } from '../api/client';
import { useGameStore } from '../stores/gameStore';

const SLOT_COLORS = [
  'border-l-blue-400',
  'border-l-red-400',
  'border-l-yellow-400',
  'border-l-green-400',
];

const NAME_RE = /^[A-Za-z0-9 _.-]+$/;

/** One-line description of each built-in player, so the choice is informed. */
export const PLAYER_INFO: Record<string, string> = {
  TilesMCTS: 'Strongest: PUCT tree search (wins 75-81% against the other search bots).',
  TilesProfiledMCTS: "Strongest search plus a learned model of each opponent's habits (no measurable gain yet).",
  TilesMinimax: 'Fast lookahead search; weaker than the others.',
  MinimaxPlayer: 'Depth-3 alpha-beta search; strong and fast.',
  MCTSPlayer: 'UCT tree search; about as strong as Minimax.',
  ConditionedMCTSPlayer: 'UCT search that simulates opponents as their inferred style.',
  ConditionedMinimaxPlayer: 'Minimax that simulates opponents as their inferred style.',
  RolloutPlayer: 'Shortlists good moves and plays out the round for each.',
  GreedyPlayer: 'One-move heuristic. A good baseline opponent.',
  RandomPlayer: 'Random legal moves. The weakest opponent.',
  ColorCollectorPlayer: 'Greedy style: collects one colour.',
  RusherPlayer: 'Greedy style: finishes lines fast.',
  RecklessPlayer: 'Greedy style: ignores floor penalties.',
  BlockerPlayer: 'Greedy style: takes what opponents need.',
  AdaptivePlayer: 'Switches style depending on the opponent.',
  AdaptiveRolloutPlayer: 'Rollout player that adapts to the opponent.',
  TDPlayer: 'Reinforcement-learning value player (about as strong as Greedy).',
  human: 'A person joins the room themselves; their moves are inferred from the board and recorded.',
};

const PRESETS: { label: string; hint: string; players: { type: string; name: string }[] }[] = [
  { label: 'Best bot vs Greedy', hint: 'A quick, one-sided demo', players: [{ type: 'TilesMCTS', name: 'Alice' }, { type: 'GreedyPlayer', name: 'Bob' }] },
  { label: 'Bot vs bot', hint: 'Two of the strongest players', players: [{ type: 'TilesMCTS', name: 'Alice' }, { type: 'MinimaxPlayer', name: 'Bob' }] },
  { label: '4-player mix', hint: 'Different styles at one table', players: [{ type: 'TilesMCTS', name: 'Alice' }, { type: 'MinimaxPlayer', name: 'Bob' }, { type: 'RusherPlayer', name: 'Charlie' }, { type: 'BlockerPlayer', name: 'Diana' }] },
  { label: 'Me vs bot', hint: 'You join the room as a human', players: [{ type: 'TilesMCTS', name: 'Alice' }, { type: 'human', name: 'Me' }] },
];

/** Everything that would make the server reject the configuration, found before the button is pressed. */
export function validateConfig(room: string, slots: PlayerSlotConfig[], knownBots: string[]): string[] {
  const problems: string[] = [];
  if (!room.trim()) problems.push('Enter a room name (or press Random).');
  else if (!NAME_RE.test(room.trim())) problems.push("The room name may only contain letters, digits, space, '_', '.' and '-'.");
  if (slots.length < 2) problems.push('Azul needs at least 2 players.');
  if (slots.length > 0 && slots.every((p) => p.type === 'human')) problems.push('Add at least one bot: the host browser is a bot.');
  const names = slots.map((p) => (p.name || '').trim().toLowerCase()).filter(Boolean);
  if (new Set(names).size !== names.length) problems.push('Player names must be different from each other.');
  slots.forEach((p, i) => {
    if (p.name && !NAME_RE.test(p.name.trim())) problems.push(`Player ${i + 1}: the name may only contain letters, digits, space, '_', '.' and '-'.`);
    if (p.type !== 'human' && knownBots.length > 0 && !knownBots.includes(p.type)) problems.push(`Player ${i + 1}: unknown bot "${p.type}".`);
  });
  return problems;
}

export default function SessionConfig({ onCreated }: { onCreated?: (id: string) => void }) {
  const { sessions, setSessions, setError, error } = useGameStore();

  const [roomName, setRoomName] = useState('');
  const [browserMode, setBrowserMode] = useState<'headless' | 'headed'>('headed');
  const [playerSlots, setPlayerSlots] = useState<PlayerSlotConfig[]>([
    { slot: 0, type: 'TilesMCTS', name: 'Alice' },
    { slot: 1, type: 'TilesMCTS', name: 'Bob' },
  ]);
  const [moveTimeout, setMoveTimeout] = useState(10);
  const [stuckAbort, setStuckAbort] = useState(3);
  const [availablePlayers, setAvailablePlayers] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    loadPlayers();
  }, []);

  async function loadPlayers() {
    try {
      const data = await api.players.list();
      setAvailablePlayers(data.players.map((p) => p.name));
    } catch {
      setAvailablePlayers(['GreedyPlayer', 'RandomPlayer']);
    }
  }

  function generateRoomName() {
    const adjectives = ['swift', 'bold', 'cool', 'zen', 'wild', 'keen', 'calm', 'epic', 'chill'];
    const nouns = ['fox', 'owl', 'wolf', 'hawk', 'bear', 'lynx', 'elk', 'tiger', 'raven'];
    const adj = adjectives[Math.floor(Math.random() * adjectives.length)];
    const noun = nouns[Math.floor(Math.random() * nouns.length)];
    const num = Math.floor(Math.random() * 100);
    setRoomName(`${adj}-${noun}-${num}`);
  }

  function addPlayerSlot() {
    if (playerSlots.length >= 4) return;
    const defaultNames = ['Alice', 'Bob', 'Charlie', 'Diana'];
    const nextName = defaultNames[playerSlots.length] || `Player${playerSlots.length + 1}`;
    setPlayerSlots([
      ...playerSlots,
      { slot: playerSlots.length, type: 'TilesMCTS', name: nextName },
    ]);
  }

  function removePlayerSlot(index: number) {
    if (playerSlots.length <= 1) return;
    setPlayerSlots(
      playerSlots.filter((_, i) => i !== index).map((p, i) => ({ ...p, slot: i }))
    );
  }

  function updateSlot(index: number, updates: Partial<PlayerSlotConfig>) {
    setPlayerSlots(
      playerSlots.map((p, i) => (i === index ? { ...p, ...updates } : p))
    );
  }

  async function createSession() {
    setTouched(true);
    if (problems.length > 0) return;
    setCreating(true);
    setError(null);
    try {
      const session = await api.sessions.create({
        room_name: roomName.trim(),
        browser_mode: browserMode,
        move_timeout_sec: moveTimeout,
        stuck_abort_sec: stuckAbort,
        players: playerSlots.map((p) => ({
          ...p,
          name: p.name?.trim() || (p.type === 'human' ? `Human_${p.slot + 1}` : `Bot_${p.slot + 1}`),
        })),
      });
      setSessions([session, ...sessions]);
      setRoomName('');
      onCreated?.(session.id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCreating(false);
    }
  }


  const problems = validateConfig(roomName, playerSlots, availablePlayers);
  const botCount = playerSlots.filter((s) => s.type !== 'human').length;
  const humanCount = playerSlots.filter((s) => s.type === 'human').length;

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Session Configuration</h1>

      <ol className="text-sm text-gray-400 list-decimal list-inside space-y-0.5" data-testid="first-run">
        <li>Pick a quick start or choose the players below, then press Create Session.</li>
        <li>Watch it in the Game Monitor (humans: join the room on buddyboardgames.com with the same room name).</li>
        <li>Open Replay to see why each move was chosen, who the players look like, and to rate the explanations.</li>
      </ol>

      {error && (
        <div role="alert" className="bg-red-900/50 border border-red-700 text-red-200 px-4 py-3 rounded-lg flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 text-sm">
            Dismiss
          </button>
        </div>
      )}

      {/* Create Session Form */}
      <div className="bg-gray-900 rounded-xl p-6 border border-gray-800 space-y-5">
        <h2 className="text-lg font-semibold text-teal-400">New Session</h2>

        <div>
          <label className="block text-sm text-gray-400 mb-1">Game Platform</label>
          <input
            type="text"
            value="https://buddyboardgames.com/azul"
            readOnly
            className="w-full bg-gray-800 text-gray-500 rounded-lg px-3 py-2 text-sm border border-gray-700"
          />
        </div>

        {/* Presets */}
        <div>
          <div className="text-sm text-gray-400 mb-1">Quick start</div>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((pr) => (
              <button key={pr.label} title={pr.hint}
                      onClick={() => setPlayerSlots(pr.players.map((p, i) => ({ slot: i, ...p })))}
                      className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs border border-gray-700">
                {pr.label}
              </button>
            ))}
          </div>
        </div>

        {/* Room Name */}
        <div>
          <label htmlFor="room-name" className="block text-sm text-gray-400 mb-1">Room name</label>
          <div className="flex gap-2">
            <input
              id="room-name"
              type="text"
              value={roomName}
              onChange={(e) => setRoomName(e.target.value)}
              placeholder="e.g. fun-room-1"
              maxLength={20}
              className="flex-1 bg-gray-800 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-700 focus:border-teal-500 focus:outline-none"
            />
            <button
              onClick={generateRoomName}
              className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition"
            >
              Random
            </button>
          </div>
        </div>

        {/* Browser Mode */}
        <div>
          <label className="block text-sm text-gray-400 mb-2">Browser Mode</label>
          <div className="flex gap-3">
            <button
              onClick={() => setBrowserMode('headless')}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
                browserMode === 'headless'
                  ? 'bg-teal-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              Headless
            </button>
            <button
              onClick={() => setBrowserMode('headed')}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
                browserMode === 'headed'
                  ? 'bg-teal-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              Headed (Watch Live)
            </button>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {browserMode === 'headed'
              ? `Each bot gets its own visible browser window (${botCount} window${botCount !== 1 ? 's' : ''}).`
              : 'No browser UI. Faster and lower resource usage.'}
          </p>
        </div>

        {/* Timeout Config */}
        <div>
          <label className="block text-sm text-gray-400 mb-2">Move Timeout</label>
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="block text-xs text-gray-500 mb-1">Max seconds per move</label>
              <input
                type="number"
                min={3}
                max={60}
                value={moveTimeout}
                onChange={(e) => setMoveTimeout(Math.max(3, parseInt(e.target.value) || 10))}
                className="w-full bg-gray-800 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-700 focus:border-teal-500 focus:outline-none"
              />
            </div>
            <div className="flex-1">
              <label className="block text-xs text-gray-500 mb-1">Abort after stuck (sec)</label>
              <input
                type="number"
                min={1}
                max={30}
                value={stuckAbort}
                onChange={(e) => setStuckAbort(Math.max(1, parseInt(e.target.value) || 3))}
                className="w-full bg-gray-800 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-700 focus:border-teal-500 focus:outline-none"
              />
            </div>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            Search bots (e.g. TilesMCTS) use at most 70% of this limit for thinking, so a low limit makes them weaker. If a bot can't make a valid move within {moveTimeout}s, and no progress for {moveTimeout + stuckAbort}s total, the session aborts with diagnostic logs.
          </p>
        </div>

        {/* Player Slots */}
        <div>
          <div className="flex justify-between items-center mb-2">
            <label className="text-sm text-gray-400">
              Players ({playerSlots.length}/4)
              {humanCount > 0 && (
                <span className="ml-2 text-yellow-400">
                  — {humanCount} human slot{humanCount > 1 ? 's' : ''}: share the room link for them to join
                </span>
              )}
            </label>
            <button
              onClick={addPlayerSlot}
              disabled={playerSlots.length >= 4}
              className="text-xs px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded-lg transition disabled:opacity-40"
            >
              + Add Player
            </button>
          </div>
          <div className="space-y-2">
            {playerSlots.map((slot, i) => (
              <div
                key={i}
                className={`flex gap-2 items-center bg-gray-800/50 rounded-lg p-2 border-l-4 ${SLOT_COLORS[i] || 'border-l-gray-500'}`}
              >
                <span className="text-xs text-gray-500 w-5 text-center font-mono">{i + 1}</span>
                <select
                  value={slot.type}
                  onChange={(e) => updateSlot(i, { type: e.target.value })}
                  className="w-40 bg-gray-800 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-700 focus:border-teal-500 focus:outline-none"
                >
                  <optgroup label="Bots">
                    {availablePlayers.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="Other">
                    <option value="human">Human (joins manually)</option>
                  </optgroup>
                </select>
                <input
                  type="text"
                  value={slot.name || ''}
                  onChange={(e) => updateSlot(i, { name: e.target.value })}
                  placeholder={slot.type === 'human' ? 'Human name' : 'Bot name'}
                  maxLength={16}
                  className="flex-1 bg-gray-800 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-700 focus:border-teal-500 focus:outline-none"
                />
                <span className="text-xs text-gray-600 w-20 text-right hidden sm:block">
                  {slot.type === 'human' ? 'manual join' : 'auto-play'}
                </span>
                <button
                  onClick={() => removePlayerSlot(i)}
                  disabled={playerSlots.length <= 1}
                  className="text-gray-500 hover:text-red-400 transition disabled:opacity-30 px-1"
                >
                  x
                </button>
              </div>
            ))}
          </div>
          <ul className="text-[11px] text-gray-500 mt-2 space-y-0.5">
            {[...new Set(playerSlots.map((p) => p.type))].map((t) => (
              <li key={t}><span className="text-gray-400">{t === 'human' ? 'Human' : t}:</span> {PLAYER_INFO[t] || 'Registered player.'}</li>
            ))}
          </ul>
        </div>

        {/* What still needs fixing */}
        {problems.length > 0 && (touched || roomName.length > 0) && (
          <ul className="text-xs text-yellow-400 space-y-0.5 list-disc list-inside" role="alert" data-testid="config-problems">
            {problems.map((p) => <li key={p}>{p}</li>)}
          </ul>
        )}

        {/* Create Button */}
        <button
          onClick={createSession}
          disabled={creating || problems.length > 0}
          className="w-full py-3 bg-teal-600 hover:bg-teal-500 rounded-lg font-semibold transition disabled:opacity-50"
        >
          {creating
            ? 'Creating...'
            : `Create Session (${botCount} bot${botCount !== 1 ? 's' : ''}${humanCount > 0 ? ` + ${humanCount} human${humanCount > 1 ? 's' : ''}` : ''})`}
        </button>
      </div>

    </div>
  );
}
