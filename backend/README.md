# TILES backend

The Python package behind TILES: the Azul rules engine, the four agents, the
turn pipeline, local and live game runners, the database, the experiments and
the API server.

Start with the [main README](../README.md) for what TILES is and how to run it.

## Setup

The launcher at the repository root (`./start.sh`, or `start.cmd` on
Windows) creates `.venv` here and installs the package for you. To set it up
by hand instead:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e '.[dev,live]'
```

## Everyday commands

```bash
tiles serve          # start the API at http://127.0.0.1:8000
tiles --help         # list every command
pytest               # run the tests
```

## Where things are

| Folder | Contents |
|---|---|
| `tiles/` | The package. The main README lists what each part does. |
| `tests/` | The pytest suite. |

## More detail

- [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) explains how the package is
  organised.
- [docs/API.md](../docs/API.md) documents the API.
- [docs/EVALUATION.md](../docs/EVALUATION.md) covers the built-in
  experiments.
