# tiles (backend)

The TILES backend package: Azul rules engine, the four-agent Decision
Stack (Validator / Tactician / Profiler / Explainer), orchestration,
SQLite ledger, rulebook RAG, simulation & experiment runners, the live
buddyboardgames.com adapter, and the FastAPI server.

See the repository root `README.md` and `docs/ARCHITECTURE.md` for the
full picture.

```bash
pip install -e '.[dev]'    # + [live] [telemetry] [llm] [rl] extras
pytest
tiles --help
```
