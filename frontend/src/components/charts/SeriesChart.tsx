import type { SeriesDTO } from "../../types";
import { BarChart } from "./BarChart";
import { LineChart } from "./LineChart";
import { Matrix } from "./Matrix";
import { formatTick } from "./palette";

/**
 * Renders an API `series` object (bar | line | matrix) and always ships
 * its table-view twin so no value is reachable only through color.
 */
export function SeriesChart({ series }: { series: SeriesDTO }) {
  const plot =
    series.kind === "line" ? (
      <LineChart
        labels={series.labels}
        series={series.data}
        xLabel={series.x_label}
        yLabel={series.y_label}
      />
    ) : series.kind === "matrix" ? (
      <Matrix
        labels={series.labels}
        rowLabels={series.row_labels}
        series={series.data}
        xLabel={series.x_label}
        yLabel={series.y_label}
      />
    ) : (
      <BarChart
        labels={series.labels}
        series={series.data}
        xLabel={series.x_label}
        yLabel={series.y_label}
      />
    );

  return (
    <div className="chart-card">
      <h4>{series.title}</h4>
      {plot}
      <details className="chart-table">
        <summary className="small muted">table view</summary>
        <table className="data-table">
          <thead>
            <tr>
              <th>{series.kind === "matrix" ? series.y_label ?? "" : "series"}</th>
              {series.labels.map((l) => (
                <th key={l}>{l}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {series.data.map((d, i) => (
              <tr key={d.name}>
                <td>{series.row_labels?.[i] ?? d.name}</td>
                {d.values.map((v, j) => (
                  <td key={j} className="num">
                    {v == null ? "—" : formatTick(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
