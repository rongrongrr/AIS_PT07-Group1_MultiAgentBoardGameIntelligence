/** A small "?" that explains a term on hover, focus or tap (title-based so it works without JS libraries). */
export default function Help({ text }: { text: string }) {
  return (
    <span
      role="note"
      tabIndex={0}
      title={text}
      aria-label={text}
      className="inline-flex items-center justify-center w-4 h-4 ml-1 rounded-full bg-gray-700 text-[10px] text-gray-300 cursor-help align-middle"
    >?</span>
  );
}

/** Plain-language definitions used across the UI. */
export const GLOSSARY = {
  elo: 'Elo is a strength rating from head-to-head results: about 100 points of difference means the stronger player wins roughly 64% of games. Small tournaments give noisy ratings.',
  confidence: 'How strongly the profiler favours this label over the other styles. It is not the chance the label is right: the model was trained on simulated bots, so treat labels on real players as hypotheses.',
  archetype: 'A recurring play style (for example Rusher: finishes lines fast; Blocker: takes what opponents need). Inferred from the moves seen so far.',
  decision: 'Time the bot spent choosing its move. The click and network time of the browser is shown separately.',
  floor: 'Tiles that could not be placed fall to the floor line and cost points; heavy floor use usually means a risky or rushed style.',
  alternatives: 'The best moves the bot considered, with its own score for each. Higher is better for the bot.',
} as const;
