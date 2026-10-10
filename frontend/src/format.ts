/** Display-text helpers: turn machine identifiers into properly cased labels. */

const ACRONYMS = new Set(["mcts", "llm", "xai", "rl", "ai", "id", "ms", "api", "ws"]);

/** "pattern_line" → "Pattern Line", "firstPlayer" → "First Player". */
export function titleCase(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .split(/\s+/)
    .map((w) =>
      ACRONYMS.has(w.toLowerCase())
        ? w.toUpperCase()
        : w.charAt(0).toUpperCase() + w.slice(1),
    )
    .join(" ");
}
