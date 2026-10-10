import { action, centerAction } from "./test/fixtures";
import {
  describeAction,
  formatDuration,
  formatNumber,
  formatPct,
  formatTime,
  playersLabel,
  sameAction,
  wallColorAt,
} from "./types";

describe("wallColorAt", () => {
  it("rotates colours along each row", () => {
    expect(wallColorAt(0, 0)).toBe("blue");
    expect(wallColorAt(0, 1)).toBe("yellow");
    expect(wallColorAt(1, 0)).toBe("white");
    expect(wallColorAt(4, 0)).toBe("yellow");
  });
});

describe("describeAction", () => {
  it("formats factory to row moves", () => {
    expect(describeAction(action)).toBe("Red: Factory 3 → Row 4");
  });
  it("formats centre to floor moves", () => {
    expect(describeAction(centerAction)).toBe("Blue: Center → Floor");
  });
  it("tolerates missing indices", () => {
    expect(
      describeAction({ ...action, source_index: null, destination_row: null }),
    ).toBe("Red: Factory 1 → Row 1");
  });
});

describe("sameAction", () => {
  it("compares every field", () => {
    expect(sameAction(action, { ...action })).toBe(true);
    expect(sameAction(action, centerAction)).toBe(false);
    expect(sameAction(action, { ...action, destination_row: 0 })).toBe(false);
  });
});

describe("formatters", () => {
  it("formatTime", () => {
    expect(formatTime(null)).toBe("—");
    expect(formatTime("garbage")).toBe("garbage");
    expect(formatTime("2026-01-02T03:04:05Z")).not.toBe("—");
  });
  it("formatDuration", () => {
    expect(formatDuration(null, null)).toBe("");
    expect(typeof formatDuration("2026-01-01T00:00:00Z", "2026-01-01T00:01:05Z")).toBe("string");
    expect(typeof formatDuration("2026-01-01T00:00:00Z", null)).toBe("string");
    expect(typeof formatDuration("nope", null)).toBe("string");
  });
  it("formatNumber", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(NaN)).toBe("—");
    expect(formatNumber(1234)).toBe((1234).toLocaleString());
    expect(formatNumber(1.234, 2)).toBe("1.23");
  });
  it("formatPct", () => {
    expect(formatPct(undefined)).toBe("—");
    expect(formatPct(0.256)).toBe("26%");
  });
  it("playersLabel", () => {
    expect(
      playersLabel([
        { name: "A", tactician: "greedy" },
        { name: "B", tactician: "mcts" },
      ]),
    ).toBe("A (greedy) vs B (mcts)");
  });
});
