import {
  MUTED_SERIES,
  SERIES_COLORS,
  SEQUENTIAL,
  formatTick,
  inkOnSequential,
  niceTicks,
  sequentialColor,
  seriesColor,
} from "./palette";

describe("palette", () => {
  it("assigns series colours in order and folds extras to muted", () => {
    expect(seriesColor(0)).toBe(SERIES_COLORS[0]);
    expect(seriesColor(99)).toBe(MUTED_SERIES);
  });
  it("maps magnitudes onto the sequential ramp", () => {
    expect(sequentialColor(0)).toBe(SEQUENTIAL[0]);
    expect(sequentialColor(1)).toBe(SEQUENTIAL[SEQUENTIAL.length - 1]);
    expect(sequentialColor(5)).toBe(SEQUENTIAL[SEQUENTIAL.length - 1]);
    expect(sequentialColor(NaN)).toBe(SEQUENTIAL[0]);
  });
  it("picks readable ink", () => {
    expect(inkOnSequential(0.9)).toBe("#ffffff");
    expect(inkOnSequential(0.1)).not.toBe("#ffffff");
  });
  it("produces nice ticks", () => {
    expect(niceTicks(0, 10)).toEqual([0, 2.5, 5, 7.5, 10]);
    expect(niceTicks(NaN, 1)).toEqual([0]);
    expect(niceTicks(0, 0)).toEqual([0, 1]);
    expect(niceTicks(3, 3)).toEqual([0, 3]);
    expect(niceTicks(-3, -3)).toEqual([-3, 0]);
  });
  it("formats ticks", () => {
    expect(formatTick(2000)).toBe("2k");
    expect(formatTick(2500)).toBe("2.5k");
    expect(formatTick(12)).toBe("12");
    expect(formatTick(0.456)).toBe("0.46");
    expect(formatTick(1.26)).toBe("1.3");
  });
});
