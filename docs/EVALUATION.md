# TILES evaluation

This document describes the eight experiments built into the app. You can run
them yourself from the Experiments view or with the `tiles` command.

## Built-in experiments

Run an experiment from the **Experiments** view in the web app, or from the
terminal:

```bash
tiles experiment list
tiles experiment run profiler_ablation --param games=20 --param simulations=300
tiles experiment run tournament --param games_per_pair=6 --output elo.json
```

Each run is saved in the database with its settings, progress and result, so
it appears in the Experiments view however it was started. A result always has
the same shape: a short summary, headline metrics, tables and charts. Unknown
settings are rejected, and `tiles experiment list` prints the settings each
experiment accepts.

| Experiment | What it measures | Settings (default) |
|---|---|---|
| `profiler_ablation` | Win rate, score margin and decision time of `greedy`, `mcts` and `mcts_profiled` against a fixed opponent that plays to block, with seats alternating. Reports how much profiling adds to the tree search. | `games` (6), `simulations` (100), `seed` (0), `tracker` (`null`; also `jsonl`, `mlflow`, `auto`) |
| `prediction_accuracy` | How often the Profiler's top prediction, and its top three, contain the opponent's actual next move, against a fixed-heuristic baseline and a uniform one, split into early, middle and late game. | `games` (10), `seed` (0) |
| `archetype_discovery` | Whether clustering, and the Profiler's own classifier, can recover five differently weighted play styles from their games. Reports cluster purity and a confusion table. | `games_per_preset` (3), `seed` (0), `k` (5) |
| `tournament` | An Elo ladder and a head-to-head win matrix between Tacticians, in two-player games with seats alternating. | `games_per_pair` (2), `simulations` (100), `seed` (0), `entrants` (`random,greedy,minimax,mcts,mcts_profiled`) |
| `search_budget_sweep` | Win rate, margin and decision time of `mcts` against `greedy` as the number of simulations grows. | `budgets` (`25,50,100,200`), `games_per_budget` (4), `seed` (0) |
| `rule_extraction` | How many rules extracted from the rulebook text match the rules engine. | `extractor` (`deterministic`; also `llm`) |
| `latency_profile` | Median, 90th-percentile and maximum time for each pipeline step (decide, validate, explain, total) per Tactician. It reads games already in the database, so play some first. | `tactician` (blank for all) |
| `xai_coverage` | The share of recorded moves that have an explanation, how often each concept tag appears, and whether the stated main reason matches the evidence. It also reads games already in the database. | `tactician` (reserved, currently ignored) |
| `heuristic_comparison` | Each named weight set for the greedy Tactician (`heuristic` variants such as `floor_averse` or `tempo_fpt`) plays against baseline greedy players at a table of 2, 3 or 4. Seats rotate, every variant gets the same deals, and each game keeps per-player statistics (score parts, floor penalty, bonuses, move mix, first-player token pick-ups, decision time). | `games_per_variant` (100), `num_players` (2), `seed` (0), `variants` (all) |
| `player_count_scaling` | One Tactician at 2, 3 and 4 player tables, in self-play and against filler opponents: scores, game length, seat advantage, and win rate against chance. Keeps the same per-game statistics. | `tactician` (`greedy`), `opponent` (`random`), `player_counts` (`2,3,4`), `games_per_setting` (100), `simulations` (100), `seed` (0) |

Four commands give a quicker, terminal-only version that prints its result
instead of saving it to the database: `tiles ablate`, `tiles tournament`,
`tiles predict-eval` and `tiles verify-rules`.

## Earlier results

An earlier version of this document recorded results from standalone scripts
that ran on a separate implementation (its own rules engine and player
library), since removed from the repository. Those results and scripts are
still in the git history at commit `dcce40b`.
