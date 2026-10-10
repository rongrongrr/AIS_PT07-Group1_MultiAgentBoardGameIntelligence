"""TILES command-line interface.

    tiles play          — run a local match and narrate it
    tiles live          — play a game on buddyboardgames.com (needs [live])
    tiles analyze       — post-hoc profile analysis of a recorded session
    tiles tournament    — round-robin with Elo standings
    tiles ablate        — profiler ablation study
    tiles predict-eval  — opponent-model prediction accuracy benchmark
    tiles verify-rules  — rulebook extraction accuracy benchmark
    tiles experiment    — list / run any registered experiment
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


def _narrate(event: dict, explain: bool) -> None:
    """Print one WS-shaped event the way a spectator would read it."""
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
            f"({record['timing'].get('decide_ms', 0):.0f}ms)"
        )
        if explain and record.get("explanation"):
            print(f"          ↳ {record['explanation']['text']}")
    elif event["type"] == "round":
        scores = event["result"].get("scores", [])
        print(f"--- round {event['round']} scored: {scores} ---")
    elif event["type"] == "game_over":
        print(
            f"=== game over: scores {event['scores']}, "
            f"winner seat {event['winner']} ==="
        )
    elif event["type"] == "status":
        extra = f"  {event['room_url']}" if event.get("room_url") else ""
        print(f"... status: {event['status']}{extra}")
    elif event["type"] == "log":
        print(f"    [{event.get('level', 'info')}] {event.get('message', '')}")


def cmd_play(args: argparse.Namespace) -> int:
    from tiles.sim.match import MatchConfig, MatchRunner

    players = [_parse_player(p) for p in args.player] or [
        {"name": "Athena", "tactician": "mcts_profiled", "config": {}},
        {"name": "Bruno", "tactician": "greedy", "config": {}},
    ]
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
    result = MatchRunner(
        config, ledger=ledger, on_event=lambda e: _narrate(e, args.explain)
    ).run()
    print(
        f"\nsession {result.session_id}: {result.steps} moves in "
        f"{result.duration_s:.1f}s"
    )
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    import asyncio

    from tiles.agents.explainer import make_explainer
    from tiles.agents.profiler import make_profiler
    from tiles.agents.tacticians import make_tactician
    from tiles.engine.live_session import LiveSeat, LiveSession, LiveSessionConfig

    players = [_parse_player(p) for p in args.player] or [
        {"name": "Athena", "tactician": "greedy", "config": {}},
        {"name": "Bruno", "tactician": "greedy", "config": {}},
    ]
    seats = [
        LiveSeat(
            p["name"],
            None if p["tactician"] == "human" else make_tactician(p["tactician"], **p["config"]),
        )
        for p in players
    ]
    ledger = None
    session_id = None
    if args.db:
        import uuid

        from tiles.ledger.store import Ledger

        ledger = Ledger(args.db)
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        ledger.create_session(
            session_id,
            mode="live",
            config={
                "mode": "live",
                "players": players,
                "profiler": args.profiler,
                "explainer": args.explainer,
                "live": {"room_name": args.room, "platform_url": args.url, "headless": not args.headed},
            },
        )
    session = LiveSession(
        LiveSessionConfig(
            room_name=args.room,
            seats=seats,
            platform_url=args.url,
            headless=not args.headed,
            move_delay_ms=args.move_delay_ms,
        ),
        on_event=lambda e: _narrate(e, args.explain),
        profiler=make_profiler(args.profiler) if args.profiler else None,
        explainer=make_explainer(args.explainer) if args.explainer else None,
        ledger=ledger,
        session_id=session_id,
    )
    print(f"room link for humans: {session.room_url}")
    summary = asyncio.run(session.run())
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("status") == "completed" else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    from tiles.agents.profiler import make_profiler
    from tiles.agents.profiler.analysis import analyze_session
    from tiles.ledger.store import Ledger

    ledger = Ledger(args.db)
    session_id = args.session
    if not session_id:
        sessions = ledger.list_sessions(limit=1)
        if not sessions:
            print("ledger is empty", file=sys.stderr)
            return 1
        session_id = sessions[0]["id"]
    row = ledger.get_session(session_id)
    if row is None:
        print(f"unknown session {session_id}", file=sys.stderr)
        return 1
    players = (row.get("config") or {}).get("players") or []
    result = analyze_session(
        ledger.get_history(session_id),
        make_profiler(args.profiler),
        player_names={i: p["name"] for i, p in enumerate(players)},
        tacticians={i: p.get("tactician") for i, p in enumerate(players)},
    )
    if args.json:
        print(json.dumps({"session_id": session_id, "profiler": args.profiler, **result}, indent=2))
        return 0
    print(f"session {session_id}: {result['moves_analyzed']} moves analyzed with {args.profiler!r}")
    for player in result["players"]:
        profile = player["profile"]
        stats = player["stats"]
        print(
            f"\n{player['player_name']} ({player['tactician']}): "
            f"{profile['archetype']} ({profile['confidence']:.0%} confidence), "
            f"{stats['moves']} moves, {stats['final_score']} points"
        )
        print(f"  {profile['summary']}")
        traits = ", ".join(f"{k}={v:.2f}" for k, v in profile["traits"].items() if k != "tempo_ms")
        print(f"  traits: {traits}")
        print(
            f"  floor rate {stats['floor_rate']:.0%} · completion {stats['completion_rate']:.0%}"
            f" · avg decision {stats['avg_decision_ms']:.0f}ms"
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
    from pathlib import Path

    from tiles.rulebook import extract_rules_deterministic, verify_rules
    from tiles.rulebook.ingest import RulebookIndex

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


def _add_player_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--player",
        action="append",
        default=[],
        help="name=tactician[:key=value,...] (repeat 2-4x; tactician 'human' = a person)",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tiles", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("play", help="run one local match")
    _add_player_arg(p)
    p.add_argument("--profiler", default="basic")
    p.add_argument("--explainer", default="template")
    p.add_argument("--no-explain", dest="explain", action="store_false")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--db", default=None, help="record to this sqlite ledger")
    p.set_defaults(func=cmd_play, explain=True)

    p = sub.add_parser("live", help="play on buddyboardgames.com (needs tiles[live])")
    _add_player_arg(p)
    p.add_argument("--room", required=True, help="room name on the platform")
    p.add_argument("--url", default="https://buddyboardgames.com/azul")
    p.add_argument("--headed", action="store_true", help="show the browsers")
    p.add_argument("--profiler", default="basic")
    p.add_argument("--explainer", default="template")
    p.add_argument("--no-explain", dest="explain", action="store_false")
    p.add_argument("--move-delay-ms", type=int, default=0)
    p.add_argument("--db", default=None, help="record to this sqlite ledger")
    p.set_defaults(func=cmd_live, explain=True)

    p = sub.add_parser("analyze", help="post-hoc profile analysis from the ledger")
    p.add_argument("--db", default="db/tiles.db")
    p.add_argument("--session", default=None, help="session id (default: latest)")
    p.add_argument("--profiler", default="basic")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("tournament", help="round-robin with Elo")
    _add_player_arg(p)
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

    try:
        from tiles.experiments.cli import add_experiment_commands
    except ImportError:  # pragma: no cover — experiments module optional
        add_experiment_commands = None
    if add_experiment_commands is not None:
        add_experiment_commands(sub)

    p = sub.add_parser("serve", help="start the API server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--db", default="db/tiles.db")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
