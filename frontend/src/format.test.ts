import { titleCase } from "./format";

describe("titleCase", () => {
  it("capitalises words and removes separators", () => {
    expect(titleCase("pattern_line")).toBe("Pattern Line");
    expect(titleCase("opponent-aware")).toBe("Opponent Aware");
    expect(titleCase("firstPlayer")).toBe("First Player");
  });

  it("upper-cases known acronyms", () => {
    expect(titleCase("mcts_profiled")).toBe("MCTS Profiled");
    expect(titleCase("llm")).toBe("LLM");
  });

  it("handles empty values", () => {
    expect(titleCase("")).toBe("");
    expect(titleCase(null)).toBe("");
    expect(titleCase(undefined)).toBe("");
  });
});
