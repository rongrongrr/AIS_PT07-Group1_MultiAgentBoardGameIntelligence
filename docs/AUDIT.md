# Final audit: bugs, unintended behaviour, gaps and enhancements

Done after the stage-2 merge by probing the running system (API with bad input, live Docker games, timing, tests and lint), not only by reading code. "Fixed" items have regression tests in `tests/test_hardening.py`, `tests/test_routes_extra.py` or `tests/test_human_tracker.py`.

## Found and fixed

| # | Finding | Impact | Fix |
|---|---|---|---|
| 1 | Search players ran synchronously inside the async game loop | While a bot thought (0.6-4 s) the event loop was frozen: the other bots, the UI WebSocket and the move timeout itself were starved, so `move_timeout_sec` could not fire for a stuck search | CPU-bound players now run in a worker thread on a copy of the state (`cpu_bound`, `sessions._decide`); a test proves the loop keeps ticking and the timeout fires |
| 2 | `TilesMCTS`'s 2.5 s budget ignored the session's move timeout | With a 1-2 s limit it could never finish in time | `set_time_limit()` hook: search budgets are capped at 70% of the limit (live check: limit 3 s, longest decision 2.1 s, no timeouts) |
| 3 | Winner was `max(scores)` | Ignored Azul's tie-break (more completed wall rows) and silently picked the first player on a true tie | `pick_winner`: score, then completed rows, then a shared win reported as "A / B" |
| 4 | Session config was barely validated | 1 player, duplicate names, unknown player types, human-only rooms, duplicate slots, `<b>` in names, `a/b?c` as a room were accepted, and failed later or typed junk into the platform | Validated at creation with a clear 422 (`tiles/validation.py`) |
| 5 | `platform_url` accepted any http(s) host | The server's browsers could be pointed at any host, including cloud-metadata addresses (SSRF) | Host allow-list (`TILES_ALLOWED_PLATFORM_HOSTS`, default buddyboardgames.com and localhost) |
| 6 | Remote models could use link-local / metadata URLs, and could register under a built-in name | SSRF; `TilesMCTS` (added after the built-in list was written) could be overwritten by a remote model | URL check, and "built-in" is now computed from the registry |
| 7 | Sessions stuck in `playing` / `lobby` after a crash or restart stayed that way forever | UI showed phantom running games | Marked aborted at startup |
| 8 | A session with a human never aborted if the human left | Chromium bots held open indefinitely | Idle timeout (`TILES_HUMAN_IDLE_TIMEOUT_S`, default 30 min) |
| 9 | Unlimited concurrent sessions | Each bot is a Chromium; a few sessions can exhaust memory | `TILES_MAX_SESSIONS` (default 3), 429 beyond it |
| 10 | "Immutable" ledger was immutable by convention only | The proposal promises immutable move recording | SQLite triggers refuse UPDATE and DELETE on `moves` |
| 11 | Wrong LLM model ids, an unverifiable API parameter, dead branches | LLM paths would have failed on first real use | Corrected |
| 12 | Unknown `/api/...` paths returned the HTML page when the UI was hosted by the API | Confusing errors | JSON 404 |
| 13 | 422 validation errors showed as "[object Object]" in the UI | Poor feedback | Error list is formatted |
| 14 | `alembic` was a dependency nothing used; `pyproject` listed 3 of ~10 real dependencies | Broken `pip install -e .` | Removed / corrected, verified in a fresh venv |
| 15 | Profile score was the score *before* the player's last move; floor use counted only moves sent straight to the floor | A finished game showed e.g. 35 instead of the final 76 points (real recorded game), and a player who overflowed pattern lines looked "conservative" | Profiles use the session's recorded final scores for completed games (and the latest snapshot otherwise, labelled "so far"); floor use now counts tiles that end on the floor including overflow, and drives the aggressive/conservative label |

## Known limitations (not bugs, but be aware)

* **The platform is a third-party dependency.** Its protocol already changed once; any change breaks live play. Mitigations: WebSocket-state-first parsing, a captured-frame fixture and `TILES_DEBUG_FRAMES`. There is no automated alarm when the site changes; the live test (`pytest -m live`) is the canary and is not in CI.
* **Two rules engines.** They are cross-checked over full random games, but only on rules both implement identically; a rules *variant* (ingested `RulesConfig`) is honoured by `tiles/azul` only. The core search players assume standard rules.
* **Bag/lid is estimated for the core search players** (unseen tiles are treated as the bag). That is exact for within-round search and an approximation for redeals.
* **Human move inference** records 24-28 of 26-29 moves per live game; moves it cannot match are logged and counted, not guessed. It has only been tested with a scripted outside client.
* **Elo and head-to-head figures are small samples** (12 and 40 games per pair, one seed). The Leaderboard file was assembled from a run's printed output.
* **Profilers are trained on simulated bots**; archetype labels on human or unseen play are hypotheses.
* **No automated UI end-to-end test** (the UI is covered by component tests and screenshots from real runs).
* **Container runs as root** (the Playwright base image's default) and has no CPU/memory limits; fine for a local demo, not for exposure.
* **One shared secret** is the only authentication; there are no per-user accounts or rate limits.

## Suggested enhancements (not done; ordered by value)

1. Run the human-centred study and train/validate the profilers on real human games (needs people).
2. Run `pytest -m live` on a schedule outside CI to detect platform changes early.
3. Add an end-to-end browser test of the UI against a fake platform (Playwright against the Docker stack). The UI now has 31 component and logic tests and screenshots from real runs (`docs/evidence/ux_*.png`), but no scripted click-through.
4. Drop to a non-root container user and set resource limits in `docker-compose.yml`.
5. Persist active-session state so a restart can resume a game instead of aborting it.
6. Make the second-engine duplication smaller by letting the live runtime use `tiles.core` for legality, once the platform parser is the only remaining `GameStateData` consumer.
7. Re-run the tournament with more deals and several seeds and publish confidence intervals in the Leaderboard.

## UI / UX pass (after the audit)

Replay: two-column layout with a sticky "why" panel, board before/after each move, a bar chart of the options weighed, keyboard control, rating progress with "next unrated", scores-only condition selector, human-move explanation. Session setup: presets, inline validation, bot descriptions. Monitor: plain-language status banner, abort reason (new `abort_reason` column, added to existing databases automatically), WebSocket auto-reconnect, confirm-before-stop, visible start/stop errors (these were silently swallowed before). App: searchable, filterable session list, tile-letter mode for colour-blind players, tab semantics, focus rings, reduced-motion, collapsible sidebar on narrow screens, `?` help on Elo / confidence / archetype, 95% intervals on the leaderboard.

Still open: a light theme, replay export (PDF/GIF), animated tile movement (the move is highlighted and the after-board is one click away), and a scripted end-to-end UI test.
