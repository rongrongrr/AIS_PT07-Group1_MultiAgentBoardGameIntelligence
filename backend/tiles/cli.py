"""TILES command-line interface.

    tiles play          — run a local match and narrate it
    tiles tournament    — round-robin with Elo standings
    tiles ablate        — profiler ablation study
    tiles predict-eval  — opponent-model prediction accuracy benchmark
    tiles verify-rules  — rulebook extraction accuracy benchmark
    tiles serve         — start the API server (+ UI when built)
"""

from __future__ import annotations

import argparse
import json
import sys


def _parse_player(spec: str) -> dict:
    """``name=tactician[:key=value,...]`` → player dict."""
    name, _, rest = spec.partition("=")
    tactician, _, config_str = rest.partition(":")
    config: dict = {}
    if config_str:
        for pair in config_str.split(","):
            key, _, value = pair.partition("=")
            try:
                config[key] = json.loads(value)
            except json.JSONDecodeError:
                config[key] = value
    return {"name": name, "tactician": tactician or "greedy", "config": config}


def cmd_play(args: argparse.Namespace) -> int:
    from tiles.sim.match import MatchConfig, MatchRunner

    players = [_parse_player(p) for p in args.player] or [
        {"name": "Athena", "tactician": "mcts_profiled", "config": {}},
        {"name": "Bruno", "tactician": "greedy", "config": {}},
    ]

    def on_event(event: dict) -> None:
        if event["type"] == "move":
            record = event["record"]
            action = record["action"]
            dest = (
                "floor"
                if action["destination"] == "floor"
                else f"row {action['destination_row'] + 1}"
            )
            source = (
                "center"
                if action["source_type"] == "center"
                else f"factory {action['source_index'] + 1}"
            )
            print(
                f"[r{record['round']:>2} #{record['step']:>3}] "
                f"{record['player_name']:<12} {action['color']:>6} "
                f"{source} -> {dest:<7} "
                f"({record['timing']['decide_ms']:.0f}ms)"
            )
            if args.explain and record.get("explanation"):
                print(f"          ↳ {record['explanation']['text']}")
        elif event["type"] == "round":
            scores = event["result"].get("scores", [])
            print(f"--- round {event['round']} scored: {scores} ---")
        elif event["type"] == "game_over":
            print(
                f"=== game over: scores {event['scores']}, "
                f"winner seat {event['winner']} ==="
            )

    config = MatchConfig(
        players=players,
        profiler=args.profiler,
        explainer=args.explainer,
        seed=args.seed,
    )
    ledger = None
    if args.db:
        from tiles.ledger.store import Ledger

        ledger = Ledger(args.db)
    result = MatchRunner(config, ledger=ledger, on_event=on_event).run()
    print(
        f"\nsession {result.session_id}: {result.steps} moves in "
        f"{result.duration_s:.1f}s"
    )
    return 0


def cmd_tournament(args: argparse.Namespace) -> int:
    from tiles.sim.tournament import run_tournament

    entrants = [_parse_player(p) for p in args.player] or [
        {"name": "random", "tactician": "random", "config": {}},
        {"name": "greedy", "tactician": "greedy", "config": {}},
        {"name": "minimax", "tactician": "minimax", "config": {}},
        {
            "name": "mcts",
            "tactician": "mcts",
            "config": {"simulations": args.simulations},
        },
        {
            "name": "mcts_profiled",
            "tactician": "mcts_profiled",
            "config": {"simulations": args.simulations},
        },
    ]

    def on_game(game: dict) -> None:
        print(
            f"game {game['game']:>3}: {game['players'][0]} vs "
            f"{game['players'][1]} -> {game['scores']} "
            f"(winner: {game['winner']})"
        )

    result = run_tournament(
        entrants,
        games_per_pair=args.games_per_pair,
        seed=args.seed,
        on_game=on_game,
    )
    print("\n" + result.table())
    if args.output:
        with open(args.output, "w") as fh:
            json.dump(result.to_dict(), fh, indent=2)
        print(f"\nwrote {args.output}")
    return 0


def cmd_ablate(args: argparse.Namespace) -> int:
    from tiles.sim.ablation import run_ablation

    results = run_ablation(
        games=args.games,
        simulations=args.simulations,
        seed=args.seed,
        tracker_backend=args.tracker,
    )
    print("\ncondition        games  win_rate  avg_margin  avg_decide_ms")
    for r in results:
        d = r.to_dict()
        print(
            f"{d['condition']:<16}{d['games']:>6}{d['win_rate']:>10.3f}"
            f"{d['avg_margin']:>12.2f}{d['avg_decision_ms']:>15.1f}"
        )
    return 0


def cmd_predict_eval(args: argparse.Namespace) -> int:
    from tiles.sim.prediction_eval import evaluate_prediction_accuracy

    report = evaluate_prediction_accuracy(games=args.games, seed=args.seed)
    print(json.dumps(report, indent=2, default=str))
    return 0


def cmd_verify_rules(_args: argparse.Namespace) -> int:
    from tiles.rulebook import extract_rules_deterministic, verify_rules
    from tiles.rulebook.ingest import RulebookIndex
    from pathlib import Path

    path = Path(__file__).parent / "rulebook" / "rulebook.md"
    index = RulebookIndex.build(str(path))
    specs = extract_rules_deterministic(index)
    report = verify_rules(specs)
    print(report.summary_table())
    return 0 if report.accuracy == 1.0 else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from tiles.server.app import create_app

    uvicorn.run(
        create_app(db_path=args.db),
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tiles", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("play", help="run one local match")
    p.add_argument(
        "--player",
        action="append",
        default=[],
        help="name=tactician[:key=value,...] (repeat 2-4x)",
    )
    p.add_argument("--profiler", default="basic")
    p.add_argument("--explainer", default="template")
    p.add_argument("--no-explain", dest="explain", action="store_false")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--db", default=None, help="record to this sqlite ledger")
    p.set_defaults(func=cmd_play, explain=True)

    p = sub.add_parser("tournament", help="round-robin with Elo")
    p.add_argument("--player", action="append", default=[])
    p.add_argument("--games-per-pair", type=int, default=4)
    p.add_argument("--simulations", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--output", default=None)
    p.set_defaults(func=cmd_tournament)

    p = sub.add_parser("ablate", help="profiler ablation study")
    p.add_argument("--games", type=int, default=10)
    p.add_argument("--simulations", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--tracker", default="auto", choices=["auto", "mlflow", "jsonl", "null"]
    )
    p.set_defaults(func=cmd_ablate)

    p = sub.add_parser("predict-eval", help="opponent-model accuracy")
    p.add_argument("--games", type=int, default=10)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_predict_eval)

    p = sub.add_parser("verify-rules", help="rulebook extraction benchmark")
    p.set_defaults(func=cmd_verify_rules)

    p = sub.add_parser("serve", help="start the API server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--db", default="db/tiles.db")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
