# Integration merge: `origin/bugfixes` → `feature/stage2`

Explicit, policy-driven integration executed on branch `integration/bugfixes-into-stage2`.

- **Source (theirs):** `origin/bugfixes` pinned at `f1e9782` ("Default theme is dark; Light and Match system are opt-in")
- **Target (ours):** `feature/stage2` at `6529c5d`
- **Merge base:** `84840bb` ("stage2")

## Policy (agreed before executing)

| Area | Source of truth | Rationale |
|---|---|---|
| `frontend/` | **stage2 (ours), 100%** | bugfixes changed the whole stack (Tailwind v4, react-router, zustand, vitest); keeping stage2's working UI until a dedicated UI migration |
| Root build files (`Dockerfile*`, `start.sh`, `docker-compose.yml`, `.dockerignore`, `README.md`, `.gitignore`) | **stage2 (ours)** | stage2's Docker one-command flow stays authoritative |
| `backend/` feature modules (ML, azul, explain, routers, models, scripts, rules_ingest, tests, docs strings) | **bugfixes (theirs)** | these are new files that do not collide with stage2's runtime |
| `backend/` live architecture (`tiles/engine/*`, `tiles/server/*`) | **stage2 (ours)** | stage2's live session engine and API remain the apps wired to the kept frontend |
| `docs/` | **bugfixes (theirs)** | additive documentation |
| `backend/tests/` | **both** | stage2's tests and bugfixes' tests both kept and green |

## Files where both sides changed (`--ours` resolution)

`.gitignore`, `README.md`, `backend/README.md`, `backend/tiles/orchestration/turn_graph.py` (their change was lint-only),
`frontend/README.md`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/App.tsx`,
`frontend/src/api/client.ts`, `frontend/.gitignore`, `frontend/index.html`, `frontend/src/main.tsx`,
`frontend/tsconfig.json`, `frontend/vite.config.ts`, `docker-compose.yml`, `backend/tiles/engine/__init__.py`
(auto-merged to an empty file by git — restored to stage2's exports).

## Modify/delete conflicts resolved to stage2 (ours)

- `backend/tiles/engine/{browser_seat,live_session,protocol,state_translator}.py`
- `backend/tiles/server/app.py`, `backend/tiles/server/__init__.py`
- `backend/tests/test_server.py`, `backend/tests/test_state_translator.py`
- `frontend/src/components/{MoveLog,XaiPanel}.tsx`, `frontend/src/styles.css`, `frontend/src/types.ts`,
  `frontend/src/views/Replay.tsx`, `frontend/src/components/{Board,Tile}.tsx`
- `Dockerfile`, `Dockerfile.live`, `start.sh`

## Renamed tests: both variants kept

bugfixes renamed `tests/test_{ledger,profiler,rl_env,rulebook,rules,tacticians}.py` to
`tests/test_core_*.py`. The integration keeps **both** the old (stage2) files and the new renamed ones, so
both suites run.

## test_api conflict (`add/add`)

- `backend/tests/test_api.py` → stage2's version (tests `tiles.server.app`)
- `backend/tests/test_api_main.py` → bugfixes' version ported as-is with a provenance header
  (tests `tiles.main`)

## Deliberately dropped (documented follow-ups)

- **34 frontend files** from bugfixes (Tailwind/zustand/router components, tests, Dockerfile, nginx config,
  assets). Deferred to a dedicated UI migration; they depend on the bugfixes stack.
- **`.github/workflows/ci.yml`** from bugfixes — its frontend job runs `npm test`/bugfixes stack and the
  docker job expects bugfixes' backend; re-add after the apps are unified.

## pyproject.toml

Union: bugfixes' real dependencies (sqlalchemy, numpy, scikit-learn, httpx, playwright) + stage2's
`live`/`telemetry`/`llm`/`rl` extras and package-data for the rulebook.

## Verification

- Backend: **544 passed, 2 skipped, 1 deselected** (`pytest`, both suites, 50s)
- Frontend: `npm run build` ✓ (stage2 stack untouched)

## Follow-ups

1. Decide the long-term fate of the two backend apps (`tiles.server.app` vs `tiles.main`) and wire
   bugfixes' features (ML players, leaderboard, profiler insights, validation) into the kept frontend.
2. Migrate the frontend to the bugfixes UI stack (or port its components) in a separate PR.
3. Update the root `README.md` architecture section once the apps are unified.
