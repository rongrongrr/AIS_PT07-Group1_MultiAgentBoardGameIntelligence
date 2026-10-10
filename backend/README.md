# tiles (backend)

The TILES backend package: Azul rules engine, the four-agent Decision
Stack (Validator / Tactician / Profiler / Explainer), orchestration,
SQLite ledger, rulebook RAG, the live buddyboardgames.com adapter,
simulation and experiment runners, and the FastAPI server.

See the repository root `README.md` for the full picture.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,rl]'          # + [live] [telemetry] [llm] extras
pytest                              # ~540 tests
tiles --help                        # play · live · analyze · tournament · ablate · experiment · serve
tiles serve                         # http://localhost:8000 (serves ../frontend/dist when built)
```

Package map:

| Package | Role |
|---|---|
| `tiles.core` | pure Azul engine (state, actions, rules, simulator, encodings) |
| `tiles.agents` | Decision Stack contracts, validator, tacticians, profiler (+ post-hoc analysis), explainer, catalog |
| `tiles.orchestration` | the per-turn pipeline (`propose` / `conclude` / `run_turn`) |
| `tiles.ledger` | append-only SQLite store: sessions, moves, rounds, profiles, experiments |
| `tiles.rulebook` | rulebook ingestion → rule specs → engine verification |
| `tiles.engine` | live play: the site's WebSocket protocol, state translation, DOM fallback, browser seats, `LiveSession` |
| `tiles.sim` | match runner, tournaments, ablation, prediction evaluation |
| `tiles.experiments` | experiment registry, background runner, eight experiment kinds, CLI |
| `tiles.telemetry` | MLflow / JSONL trackers |
| `tiles.rl` | PettingZoo AEC environment |
| `tiles.server` | FastAPI app factory, session manager, stats, routers |
