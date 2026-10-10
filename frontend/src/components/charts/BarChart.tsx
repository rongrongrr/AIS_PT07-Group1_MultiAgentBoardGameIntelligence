import type { SeriesDataDTO } from "../../types";
import { Legend } from "./Legend";
import { CHROME, formatTick, niceTicks, seriesColor } from "./palette";

const W = 640;
const MARGIN = { top: 14, right: 12, bottom: 44, left: 48 };
const MAX_BAR = 24;
const GAP = 2;
const RADIUS = 4;

/** Bar path with a 4px rounded data-end and a square baseline end. */
function barPath(x: number, yTop: number, yBottom: number, w: number, up: boolean) {
  const r = Math.min(RADIUS, w / 2, Math.abs(yBottom - yTop));
  if (up) {
    // rounded top corners
    return `M${x},${yBottom} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + w - r} Q${x + w},${yTop} ${x + w},${yTop + r} V${yBottom} Z`;
  }
  // negative bar: rounded bottom corners
  return `M${x},${yTop} V${yBottom - r} Q${x},${yBottom} ${x + r},${yBottom} H${x + w - r} Q${x + w},${yBottom} ${x + w},${yBottom - r} V${yTop} Z`;
}

export function BarChart({
  labels,
  series,
  yLabel,
  xLabel,
  height = 240,
  format = formatTick,
}: {
  labels: string[];
  series: SeriesDataDTO[];
  yLabel?: string;
  xLabel?: string;
  height?: number;
  format?: (v: number) => string;
}) {
  const values = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  if (labels.length === 0 || values.length === 0) {
    return <p className="muted small">No data to plot.</p>;
  }
  const dataMin = Math.min(0, ...values);
  const dataMax = Math.max(0, ...values);
  const ticks = niceTicks(dataMin, dataMax, 4);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const plotW = W - MARGIN.left - MARGIN.right;
  const band = plotW / labels.length;
  // Rotate only when horizontal labels would collide (≈7px per glyph);
  // rotated labels hang lower, so reserve extra bottom margin for them.
  const longest = Math.max(...labels.map((l) => Math.min(l.length, 18)));
  const rotate = labels.length > 6 || longest * 7 > band - 8;
  const bottom = rotate ? MARGIN.bottom + Math.min(70, longest * 4) : MARGIN.bottom;
  const H = height + (bottom - MARGIN.bottom);
  const plotH = H - MARGIN.top - bottom;
  const y = (v: number) =>
    MARGIN.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;
  const inner = band * 0.72;
  const barW = Math.min(MAX_BAR, Math.max(4, inner / series.length - GAP));
  const groupW = barW * series.length + GAP * (series.length - 1);

  // Label only the extreme (largest magnitude) bar per series.
  const extremes = series.map((s) => {
    let best = -1;
    let bestAbs = -1;
    s.values.forEach((v, i) => {
      if (v != null && Math.abs(v) > bestAbs) {
        bestAbs = Math.abs(v);
        best = i;
      }
    });
    return best;
  });

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="chart-svg"
        role="img"
        aria-label={yLabel ?? "bar chart"}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={MARGIN.left}
              x2={W - MARGIN.right}
              y1={y(t)}
              y2={y(t)}
              stroke={t === 0 ? CHROME.axis : CHROME.grid}
              strokeWidth={1}
            />
            <text
              x={MARGIN.left - 6}
              y={y(t) + 4}
              textAnchor="end"
              className="chart-tick"
            >
              {format(t)}
            </text>
          </g>
        ))}
        {labels.map((label, li) => {
          const x0 = MARGIN.left + band * li + (band - groupW) / 2;
          return (
            <g key={label}>
              <rect
                x={MARGIN.left + band * li}
                y={MARGIN.top}
                width={band}
                height={plotH}
                fill="transparent"
                className="chart-hit"
              />
              {series.map((s, si) => {
                const v = s.values[li];
                if (v == null) return null;
                const x = x0 + si * (barW + GAP);
                const top = Math.min(y(v), y(0));
                const bottom = Math.max(y(v), y(0));
                const labelled = extremes[si] === li;
                return (
                  <g key={s.name} className="bar">
                    <path
                      d={barPath(x, top, bottom, barW, v >= 0)}
                      fill={seriesColor(si)}
                    >
                      <title>{`${s.name} · ${label}: ${format(v)}`}</title>
                    </path>
                    {labelled && (
                      <text
                        x={x + barW / 2}
                        y={v >= 0 ? top - 4 : bottom + 11}
                        textAnchor="middle"
                        className="chart-value"
                      >
                        {format(v)}
                      </text>
                    )}
                  </g>
                );
              })}
              <text
                x={MARGIN.left + band * li + band / 2}
                y={H - bottom + 16}
                textAnchor={rotate ? "end" : "middle"}
                transform={
                  rotate
                    ? `rotate(-32 ${MARGIN.left + band * li + band / 2} ${H - bottom + 16})`
                    : undefined
                }
                className="chart-tick"
              >
                {label.length > 18 ? `${label.slice(0, 17)}…` : label}
              </text>
            </g>
          );
        })}
        {yLabel && (
          <text
            x={MARGIN.left}
            y={MARGIN.top - 4}
            className="chart-axis-label"
          >
            {yLabel}
          </text>
        )}
        {xLabel && !rotate && (
          <text
            x={W - MARGIN.right}
            y={H - 4}
            textAnchor="end"
            className="chart-axis-label"
          >
            {xLabel}
          </text>
        )}
      </svg>
      <Legend names={series.map((s) => s.name)} />
    </div>
  );
}
