import type { GameStateDTO, PlayerBoardDTO } from "../types";
import { FLOOR_PENALTIES, wallColorAt } from "../types";
import { Slot, Tile } from "./Tile";

function Factory({ tiles, index }: { tiles: string[]; index: number }) {
  return (
    <div className="factory" title={`factory ${index + 1}`}>
      <div className="factory-tiles">
        {tiles.length === 0 ? (
          <span className="muted small">—</span>
        ) : (
          tiles.map((t, i) => <Tile key={i} tile={t as never} />)
        )}
      </div>
      <div className="factory-label">F{index + 1}</div>
    </div>
  );
}

function PlayerBoardView({
  board,
  active,
  index,
}: {
  board: PlayerBoardDTO;
  active: boolean;
  index: number;
}) {
  return (
    <div className={`player-board${active ? " player-board-active" : ""}`}>
      <div className="player-board-header">
        <span className="player-name">
          {board.name || `player ${index + 1}`}
          {board.has_first_player_token && (
            <span className="fpt-badge" title="holds first player token">
              1st
            </span>
          )}
        </span>
        <span className="player-score">{board.score}</span>
      </div>
      <div className="board-grid">
        <div className="pattern-lines">
          {Array.from({ length: 5 }, (_, row) => {
            const line = board.pattern_lines[row] ?? [];
            const capacity = row + 1;
            return (
              <div key={row} className="pattern-row">
                {Array.from({ length: capacity }, (_, i) => {
                  // Tiles fill from the right visually.
                  const tileIdx = i - (capacity - line.length);
                  return tileIdx >= 0 && line[tileIdx] ? (
                    <Tile key={i} tile={line[tileIdx]} size="sm" />
                  ) : (
                    <Slot key={i} size="sm" />
                  );
                })}
              </div>
            );
          })}
        </div>
        <div className="wall">
          {Array.from({ length: 5 }, (_, r) => (
            <div key={r} className="wall-row">
              {Array.from({ length: 5 }, (_, c) => (
                <Slot
                  key={c}
                  color={wallColorAt(r, c)}
                  filled={Boolean(board.wall?.[r]?.[c])}
                  size="sm"
                />
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="floor-line">
        {FLOOR_PENALTIES.map((p, i) => (
          <div key={i} className="floor-slot">
            {board.floor_line[i] ? (
              <Tile tile={board.floor_line[i]} size="sm" />
            ) : (
              <Slot size="sm" />
            )}
            <span className="floor-penalty">{p}</span>
          </div>
        ))}
        {board.floor_line.length > FLOOR_PENALTIES.length && (
          <span className="muted small">
            +{board.floor_line.length - FLOOR_PENALTIES.length} overflow
          </span>
        )}
      </div>
    </div>
  );
}

export function Board({ state }: { state: GameStateDTO }) {
  return (
    <div className="board-area">
      <div className="supply-row">
        <span className="round-badge">Round {state.round}</span>
        <span className={`phase-badge phase-${state.phase}`}>
          {state.phase.replace("_", " ")}
        </span>
        <span className="muted small">
          bag {state.bag.reduce((a, b) => a + b, 0)} · lid{" "}
          {state.lid.reduce((a, b) => a + b, 0)}
        </span>
      </div>
      <div className="factories-row">
        {state.factories.map((f, i) => (
          <Factory key={i} tiles={f} index={i} />
        ))}
        <div className="center-pool">
          <div className="factory-tiles">
            {state.center_pool.length === 0 ? (
              <span className="muted small">empty</span>
            ) : (
              state.center_pool.map((t, i) => <Tile key={i} tile={t} />)
            )}
          </div>
          <div className="factory-label">center</div>
        </div>
      </div>
      <div className="players-row">
        {state.players.map((p, i) => (
          <PlayerBoardView
            key={i}
            board={p}
            index={i}
            active={state.current_player === i && state.phase === "drafting"}
          />
        ))}
      </div>
    </div>
  );
}
