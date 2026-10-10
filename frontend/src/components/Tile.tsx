import type { TileName } from "../types";

export function Tile({
  tile,
  size = "md",
  dimmed = false,
}: {
  tile: TileName;
  size?: "sm" | "md";
  dimmed?: boolean;
}) {
  if (tile === "firstPlayer") {
    return (
      <span className={`tile tile-fpt tile-${size}`} title="first player token">
        1
      </span>
    );
  }
  return (
    <span
      className={`tile tile-${tile} tile-${size}${dimmed ? " tile-dim" : ""}`}
      title={tile}
    />
  );
}

/** An empty tile slot (pattern line / wall placeholder). */
export function Slot({
  color,
  size = "md",
  filled = false,
}: {
  color?: TileName;
  size?: "sm" | "md";
  filled?: boolean;
}) {
  if (color && filled) return <Tile tile={color} size={size} />;
  if (color) return <Tile tile={color} size={size} dimmed />;
  return <span className={`tile tile-empty tile-${size}`} />;
}
