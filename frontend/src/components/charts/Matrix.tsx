import type { SeriesDataDTO } from "../../types";
import { formatTick, inkOnSequential, sequentialColor } from "./palette";

/** Heatmap: rows = series, columns = labels; one-hue sequential ramp. */
export function Matrix({
  labels,
  rowLabels,
  series,
  xLabel,
  yLabel,
  format = formatTick,
}: {
  labels: string[];
  rowLabels?: string[];
  series: SeriesDataDTO[];
  xLabel?: string;
  yLabel?: string;
  format?: (v: number) => string;
}) {
  const rows = rowLabels && rowLabels.length === series.length
    ? rowLabels
    : series.map((s) => s.name);
  const values = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  if (labels.length === 0 || values.length === 0) {
    return <p className="muted small">No data to plot.</p>;
  }
  const max = Math.max(...values, 0) || 1;
  return (
    <div className="chart matrix-wrap">
      <table className="matrix">
        <thead>
          <tr>
            <th className="matrix-corner">
              {yLabel && <span className="muted small">{yLabel} ↓</span>}
              {xLabel && <span className="muted small"> {xLabel} →</span>}
            </th>
            {labels.map((l) => (
              <th key={l}>{l}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {series.map((s, ri) => (
            <tr key={s.name}>
              <th>{rows[ri]}</th>
              {labels.map((l, ci) => {
                const v = s.values[ci];
                const t = v == null ? 0 : v / max;
                return (
                  <td
                    key={l}
                    style={{
                      background: v == null ? "transparent" : sequentialColor(t),
                      color: inkOnSequential(t),
                    }}
                    title={`${rows[ri]} × ${l}: ${v == null ? "—" : format(v)}`}
                  >
                    {v == null ? "—" : format(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
