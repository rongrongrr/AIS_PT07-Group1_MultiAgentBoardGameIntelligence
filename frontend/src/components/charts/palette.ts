/**
 * Chart palette (validated reference instance from the dataviz method).
 * Categorical slots are assigned in fixed order and never cycled past 8;
 * extra series fold into the muted gray.
 */

export const SERIES_COLORS = [
  "#1f5fa8", // blue
  "#d2552b", // orange
  "#2a9d8f", // aqua
  "#e0a526", // yellow
  "#b5446e", // magenta
  "#5b8c3a", // green
  "#4a3aa7", // violet
  "#c0392b", // red
];

/** Sequential blue ramp, light → dark (steps 100..700). */
export const SEQUENTIAL = [
  "#cde2fb",
  "#b7d3f6",
  "#9ec5f4",
  "#86b6ef",
  "#6da7ec",
  "#5598e7",
  "#3987e5",
  "#2a78d6",
  "#256abf",
  "#1c5cab",
  "#184f95",
  "#104281",
  "#0d366b",
];

export const CHROME = {
  surface: "#fffaf0",
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  muted: "#898781",
  secondary: "#52514e",
  ink: "#0b0b0b",
};

export const MUTED_SERIES = "#b4b2aa";

export function seriesColor(index: number): string {
  return index < SERIES_COLORS.length ? SERIES_COLORS[index] : MUTED_SERIES;
}

/** Color for a magnitude in [0, 1] on the sequential ramp. */
export function sequentialColor(t: number): string {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  const idx = Math.round(clamped * (SEQUENTIAL.length - 1));
  return SEQUENTIAL[idx];
}

/** Ink to put on top of a sequential fill (white on the dark half). */
export function inkOnSequential(t: number): string {
  return t > 0.55 ? "#ffffff" : CHROME.ink;
}

/** "Nice" tick values spanning [min, max] (always includes 0 if in range). */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0];
  if (min === max) {
    if (min === 0) return [0, 1];
    return min > 0 ? [0, min] : [min, 0];
  }
  const span = max - min;
  const rough = span / count;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const candidates = [1, 2, 2.5, 5, 10];
  let step = pow;
  for (const c of candidates) {
    if (rough <= c * pow) {
      step = c * pow;
      break;
    }
  }
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) {
    ticks.push(Number(v.toFixed(10)));
  }
  return ticks;
}

export function formatTick(v: number): string {
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(v % 1000 === 0 ? 0 : 1)}k`;
  if (Number.isInteger(v)) return v.toLocaleString();
  return v.toFixed(Math.abs(v) < 1 ? 2 : 1);
}
