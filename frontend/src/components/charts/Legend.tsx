import { titleCase } from "../../format";
import { seriesColor } from "./palette";

/** Legend is always present for two or more series; a single series needs none. */
export function Legend({ names }: { names: string[] }) {
  if (names.length < 2) return null;
  return (
    <ul className="chart-legend">
      {names.map((name, i) => (
        <li key={name}>
          <span
            className="legend-swatch"
            style={{ background: seriesColor(i) }}
            aria-hidden
          />
          {titleCase(name)}
        </li>
      ))}
    </ul>
  );
}
