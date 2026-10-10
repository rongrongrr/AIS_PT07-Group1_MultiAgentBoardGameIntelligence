import { render, screen } from "@testing-library/react";
import { BarChart } from "./BarChart";
import { Legend } from "./Legend";
import { LineChart } from "./LineChart";
import { Matrix } from "./Matrix";
import { SeriesChart } from "./SeriesChart";

const data = [
  { name: "alpha_one", values: [1, 2, null] },
  { name: "beta", values: [-1, 3, 2] },
];

describe("Legend", () => {
  it("is hidden for a single series", () => {
    const { container } = render(<Legend names={["a"]} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("lists properly cased names", () => {
    render(<Legend names={["alpha_one", "beta"]} />);
    expect(screen.getByText("Alpha One")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });
});

describe("BarChart", () => {
  it("shows a placeholder without data", () => {
    render(<BarChart labels={[]} series={[]} />);
    expect(screen.getByText("No data to plot.")).toBeInTheDocument();
  });
  it("draws bars, negative bars and axis labels", () => {
    const { container } = render(
      <BarChart
        labels={["a", "b", "c"]}
        series={data}
        xLabel="X axis"
        yLabel="Y axis"
        format={(v) => `${v}!`}
      />,
    );
    expect(container.querySelectorAll("path").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("X axis")).toBeInTheDocument();
    expect(screen.getByText("Y axis")).toBeInTheDocument();
  });
  it("rotates crowded labels", () => {
    const labels = Array.from({ length: 10 }, (_, i) => `a rather long label ${i}`);
    const { container } = render(
      <BarChart labels={labels} series={[{ name: "s", values: labels.map((_, i) => i) }]} />,
    );
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

describe("LineChart", () => {
  it("shows a placeholder without data", () => {
    render(<LineChart labels={["a"]} series={[{ name: "s", values: [null] }]} />);
    expect(screen.getByText("No data to plot.")).toBeInTheDocument();
  });
  it("draws lines, markers and annotations", () => {
    const { container } = render(
      <LineChart
        labels={["1", "2", "3"]}
        series={data}
        xLabel="Step"
        yLabel="Score"
        annotations={[{ index: 1, label: "Builder" }]}
      />,
    );
    expect(container.querySelectorAll("path").length).toBeGreaterThan(0);
    expect(screen.getByText("Builder")).toBeInTheDocument();
  });
  it("supports unzeroed axes without markers", () => {
    const { container } = render(
      <LineChart
        labels={["1", "2"]}
        series={[{ name: "s", values: [5, 9] }]}
        zeroBased={false}
        markers={false}
      />,
    );
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

describe("Matrix", () => {
  it("shows a placeholder without data", () => {
    render(<Matrix labels={[]} series={[]} />);
    expect(screen.getByText("No data to plot.")).toBeInTheDocument();
  });
  it("renders cells with row labels", () => {
    render(
      <Matrix
        labels={["x", "y"]}
        rowLabels={["Row A", "Row B"]}
        series={[
          { name: "a", values: [1, null] },
          { name: "b", values: [2, 4] },
        ]}
        xLabel="Cols"
        yLabel="Rows"
      />,
    );
    expect(screen.getByText("Row A")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });
  it("falls back to series names when row labels do not match", () => {
    render(
      <Matrix labels={["x"]} rowLabels={["only"]} series={[{ name: "a", values: [1] }, { name: "b", values: [1] }]} />,
    );
    expect(screen.getByText("a")).toBeInTheDocument();
  });
});

describe("SeriesChart", () => {
  const base = { title: "Chart Title", labels: ["a", "b", "c"], data };
  it.each(["bar", "line", "matrix", "other"])("renders %s series with a table twin", (kind) => {
    render(<SeriesChart series={{ ...base, kind, row_labels: ["R1", "R2"], y_label: "Y" }} />);
    expect(screen.getByText("Chart Title")).toBeInTheDocument();
    expect(screen.getByText("Table view")).toBeInTheDocument();
    expect(screen.getAllByText("R1").length).toBeGreaterThan(0);
  });
  it("shows dashes for missing values in the table", () => {
    render(<SeriesChart series={{ ...base, kind: "bar" }} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
