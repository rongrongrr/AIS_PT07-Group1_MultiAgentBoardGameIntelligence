import type { SeriesDataDTO } from "../../types";
import { Legend } from "./Legend";
import { CHROME, formatTick, niceTicks, seriesColor } from "./palette";

const W = 640;
const MARGIN = { top: 14, right: 16, bottom: 40, left: 48 };

export interface Annotation {
  /** Index into labels. */
  index: number;
  label: string;
}

export function LineChart({
  labels,
  series,
  yLabel,
  xLabel,
  height = 240,
  format = formatTick,
  annotations = [],
  markers = true,
  zeroBased = true,
}: {
  labels: string[];
  series: SeriesDataDTO[];
  yLabel?: string;
  xLabel?: string;
  height?: number;
  format?: (v: number) => string;
  annotations?: Annotation[];
  markers?: boolean;
  zeroBased?: boolean;
}) {
  const values = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  if (labels.length === 0 || values.length === 0) {
    return <p className="muted small">No data to plot.</p>;
  }
  const dataMin = zeroBased ? Math.min(0, ...values) : Math.min(...values);
  const dataMax = zeroBased ? Math.max(0, ...values) : Math.max(...values);
  const ticks = niceTicks(dataMin, dataMax, 4);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const plotW = W - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;
  const n = labels.length;
  const x = (i: number) =>
    MARGIN.left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) =>
    MARGIN.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

  // x tick labels: at most ~8, evenly sampled.
  const every = Math.max(1, Math.ceil(n / 8));
  const showMarkers = markers && n <= 60;

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${W} ${height}`}
        className="chart-svg"
        role="img"
        aria-label={yLabel ?? "line chart"}
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
        {labels.map((label, i) =>
          i % every === 0 || i === n - 1 ? (
            <text
              key={i}
              x={x(i)}
              y={height - MARGIN.bottom + 16}
              textAnchor="middle"
              className="chart-tick"
            >
              {label.length > 12 ? `${label.slice(0, 11)}…` : label}
            </text>
          ) : null,
        )}
        {annotations.map((a, i) => (
          <g key={`${a.index}-${i}`}>
            <line
              x1={x(a.index)}
              x2={x(a.index)}
              y1={MARGIN.top}
              y2={MARGIN.top + plotH}
              stroke={CHROME.axis}
              strokeWidth={1}
            />
            <text
              x={x(a.index) + 3}
              y={MARGIN.top + 10 + (i % 3) * 11}
              className="chart-annotation"
            >
              {a.label}
            </text>
          </g>
        ))}
        {series.map((s, si) => {
          const segments: string[] = [];
          let current: string[] = [];
          s.values.forEach((v, i) => {
            if (v == null) {
              if (current.length) segments.push(current.join(" "));
              current = [];
              return;
            }
            current.push(`${current.length ? "L" : "M"}${x(i)},${y(v)}`);
          });
          if (current.length) segments.push(current.join(" "));
          return (
            <g key={s.name}>
              {segments.map((d, i) => (
                <path
                  key={i}
                  d={d}
                  fill="none"
                  stroke={seriesColor(si)}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}
              {s.values.map((v, i) =>
                v == null ? null : (
                  <circle
                    key={i}
                    cx={x(i)}
                    cy={y(v)}
                    r={showMarkers ? 4 : 2}
                    fill={seriesColor(si)}
                    stroke={CHROME.surface}
                    strokeWidth={2}
                    className="chart-marker"
                  >
                    <title>{`${s.name} · ${labels[i]}: ${format(v)}`}</title>
                  </circle>
                ),
              )}
            </g>
          );
        })}
        {yLabel && (
          <text x={MARGIN.left} y={MARGIN.top - 4} className="chart-axis-label">
            {yLabel}
          </text>
        )}
        {xLabel && (
          <text
            x={W - MARGIN.right}
            y={height - 4}
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
