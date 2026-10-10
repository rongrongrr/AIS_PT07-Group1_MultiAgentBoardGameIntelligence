import type { GameStateData, Session } from '../api/client';

export interface StatusView {
  tone: 'info' | 'busy' | 'ok' | 'warn' | 'bad';
  text: string;
}

const TONES: Record<StatusView['tone'], string> = {
  info: 'bg-gray-800/60 border-gray-700 text-gray-300',
  busy: 'bg-teal-900/30 border-teal-800 text-teal-200',
  ok: 'bg-blue-900/30 border-blue-800 text-blue-200',
  warn: 'bg-yellow-900/30 border-yellow-800 text-yellow-200',
  bad: 'bg-red-900/30 border-red-800 text-red-200',
};

/** Plain-language description of what the session is doing right now. */
export function describeStatus(
  session: Session | null,
  state: GameStateData | null,
  moveCount: number,
  connected: boolean,
): StatusView {
  if (!session) return { tone: 'info', text: 'Loading session...' };
  const humans = session.player_config.filter((p) => p.type === 'human');
  switch (session.status) {
    case 'created':
      return { tone: 'info', text: 'Not started yet. Press Start to open one browser per bot and join the room.' };
    case 'lobby':
      return humans.length > 0
        ? {
            tone: 'warn',
            text: `Waiting for ${humans.map((h) => h.name || 'a human').join(', ')} to join room "${session.room_name}" on buddyboardgames.com. The game starts once everyone is in.`,
          }
        : { tone: 'busy', text: 'The bots are joining the room...' };
    case 'playing': {
      if (!connected) return { tone: 'warn', text: 'Live updates are disconnected; reconnecting. The game itself keeps running.' };
      const turn = state?.current_turn;
      if (!turn) return { tone: 'busy', text: `Playing (${moveCount} moves so far). Waiting for the first board...` };
      const slot = session.player_config.find((p) => (p.name || '') === turn);
      if (slot?.type === 'human') return { tone: 'warn', text: `Waiting for ${turn} (human) to move. Moves are recorded as they happen.` };
      return { tone: 'busy', text: `${turn}${slot ? ` (${slot.type})` : ''} is choosing a move. Round ${state?.round ?? '?'}, ${moveCount} moves so far.` };
    }
    case 'completed':
      return { tone: 'ok', text: `Finished after ${moveCount} moves${session.winner ? `; winner: ${session.winner}` : ''}. Open Replay to see why each move was chosen.` };
    case 'aborted':
      return { tone: 'bad', text: `Aborted: ${session.abort_reason || 'no reason was recorded'}.` };
    default:
      return { tone: 'info', text: session.status };
  }
}

export default function StatusBanner({ view }: { view: StatusView }) {
  return (
    <div role="status" aria-live="polite" data-testid="status-banner"
         className={`rounded-lg border px-4 py-2 text-sm ${TONES[view.tone]}`}>
      {view.text}
    </div>
  );
}
