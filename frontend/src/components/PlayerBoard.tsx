import type { PlayerState } from '../api/client';

const TILE_COLORS: Record<string, string> = {
  blue: 'bg-[#67c0dd]',
  yellow: 'bg-[#ffff59]',
  red: 'bg-[#f08080]',
  black: 'bg-[#90ee90]',
  white: 'bg-white',
  firstPlayer: 'bg-[#7fffd4]',
};

const TILE_BORDERS: Record<string, string> = {
  blue: 'border-blue-400',
  yellow: 'border-yellow-400',
  red: 'border-red-400',
  black: 'border-green-400',
  white: 'border-gray-300',
};

// Standard Azul wall pattern — which color goes where
const WALL_PATTERN = [
  ['blue', 'yellow', 'red', 'black', 'white'],
  ['white', 'blue', 'yellow', 'red', 'black'],
  ['black', 'white', 'blue', 'yellow', 'red'],
  ['red', 'black', 'white', 'blue', 'yellow'],
  ['yellow', 'red', 'black', 'white', 'blue'],
];

const FLOOR_PENALTIES = [-1, -1, -2, -2, -2, -3, -3];

interface Props {
  player: PlayerState;
  isCurrentTurn: boolean;
  compact?: boolean;
}

function TileCell({ color, size = 'md' }: { color?: string | null; size?: 'sm' | 'md' }) {
  const s = size === 'sm' ? 'w-4 h-4' : 'w-6 h-6';
  if (!color) {
    return <div className={`${s} rounded-sm bg-gray-800 border border-gray-700`} />;
  }
  return (
    <div
      className={`${s} rounded-sm ${TILE_COLORS[color] || 'bg-gray-600'} border ${TILE_BORDERS[color] || 'border-gray-500'}`}
      title={color}
    />
  );
}

export default function PlayerBoard({ player, isCurrentTurn, compact }: Props) {
  const tileSize = compact ? 'sm' : 'md';

  return (
    <div
      className={`bg-gray-900 rounded-xl p-4 border ${
        isCurrentTurn ? 'border-teal-500 shadow-lg shadow-teal-500/10' : 'border-gray-800'
      }`}
    >
      {/* Header */}
      <div className="flex justify-between items-center mb-3">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm">{player.name}</span>
          {player.system_tag && (
            <span className="text-xs text-gray-500">({player.system_tag})</span>
          )}
          {isCurrentTurn && (
            <span className="text-xs px-2 py-0.5 bg-teal-700 text-teal-200 rounded-full animate-pulse">
              Playing
            </span>
          )}
        </div>
        <span className="text-lg font-bold text-teal-400">{player.score}</span>
      </div>

      <div className="flex gap-4">
        {/* Pattern Lines */}
        <div className="space-y-1">
          <div className="text-xs text-gray-500 mb-1">Pattern Lines</div>
          {player.pattern_lines.map((row, rowIdx) => (
            <div key={rowIdx} className="flex gap-0.5 justify-end">
              {/* Empty spacers for alignment */}
              {Array.from({ length: 4 - rowIdx }).map((_, i) => (
                <div key={`s${i}`} className={tileSize === 'sm' ? 'w-4' : 'w-6'} />
              ))}
              {/* Actual slots */}
              {Array.from({ length: rowIdx + 1 }).map((_, colIdx) => {
                const tileIdx = rowIdx - colIdx; // fill from right
                const color = row[tileIdx] || null;
                return <TileCell key={colIdx} color={color} size={tileSize} />;
              })}
            </div>
          ))}
        </div>

        {/* Wall */}
        <div className="space-y-1">
          <div className="text-xs text-gray-500 mb-1">Wall</div>
          {WALL_PATTERN.map((wallRow, rowIdx) => (
            <div key={rowIdx} className="flex gap-0.5">
              {wallRow.map((color, colIdx) => (
                <div
                  key={colIdx}
                  className={`${tileSize === 'sm' ? 'w-4 h-4' : 'w-6 h-6'} rounded-sm border ${
                    player.wall[rowIdx]?.[colIdx]
                      ? `${TILE_COLORS[color]} ${TILE_BORDERS[color]}`
                      : `bg-gray-800/30 border-gray-700/50`
                  }`}
                  title={`${color}${player.wall[rowIdx]?.[colIdx] ? ' (placed)' : ''}`}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Floor Line */}
      <div className="mt-3">
        <div className="text-xs text-gray-500 mb-1">Floor</div>
        <div className="flex gap-1">
          {FLOOR_PENALTIES.map((penalty, i) => (
            <div key={i} className="text-center">
              <TileCell
                color={player.floor_line[i] || null}
                size={tileSize}
              />
              <div className="text-[10px] text-red-400 mt-0.5">{penalty}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Factory display component
export function FactoryDisplay({ tiles }: { tiles: string[]; index: number }) {
  return (
    <div className="bg-gray-800 rounded-lg p-2 border border-gray-700 inline-flex flex-wrap gap-1 w-16 h-16 items-center justify-center">
      {tiles.length === 0 ? (
        <span className="text-xs text-gray-600">Empty</span>
      ) : (
        tiles.map((color, i) => (
          <TileCell key={i} color={color} size="sm" />
        ))
      )}
    </div>
  );
}

// Center pool display
export function CenterPoolDisplay({ tiles }: { tiles: string[] }) {
  if (tiles.length === 0) return null;
  return (
    <div className="bg-gray-800/50 rounded-lg p-3 border border-gray-700 flex flex-wrap gap-1 justify-center">
      {tiles.map((color, i) => (
        <TileCell key={i} color={color} size="sm" />
      ))}
    </div>
  );
}
