# tiles (backend)

The TILES backend package. Two cooperating halves (see [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) section 6):

- the **live runtime**: FastAPI app (`tiles/main.py`, `tiles/routers/`), Playwright bots (`tiles/engine/`), the Machine Players
  (`tiles/ml/`), rationales (`tiles/explain/`), rule ingestion (`tiles/rules_ingest/`) and MLflow logging;
- the **Decision Stack** on the fast core engine: `tiles/core`, `tiles/agents` (Tactician / Profiler / Explainer / Validator),
  `tiles/orchestration`, `tiles/ledger`, `tiles/sim`, `tiles/rl`, `tiles/rulebook`, joined to the live runtime by `tiles/bridge.py`.

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt && playwright install chromium     # what Docker installs
# or: pip install -e '.[ml,telemetry,rl,dev]'                     # gives the `tiles` command
python -m pytest                                     # offline tests, coverage floor 80%
tiles serve                                          # API on http://127.0.0.1:8000 (docs at /docs)
tiles --help                                         # play | tournament | ablate | predict-eval | verify-rules
```

Trained models and tournament results are read from `backend/models/` (use an editable install or run from this directory).
Everything else - quick start, players, API, limitations - is in the [root README](../README.md).
