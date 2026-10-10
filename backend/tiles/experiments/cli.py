"""``tiles experiment`` CLI commands.

    tiles experiment list
    tiles experiment run <kind> [--param k=v ...] [--db path] [--output file]

Wired into the main parser by ``add_experiment_commands`` (called from
``tiles.cli``). Runs go through the same ``ExperimentManager`` as the
server, so results land in the ledger and show up in the UI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

from .registry import list_specs
from .runner import ExperimentManager

DEFAULT_DB = "db/tiles.db"


def _parse_param(text: str) -> tuple:
    key, sep, value = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected key=value, got {text!r}")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value
    return key.strip(), parsed


def _format_cell(value) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if value != int(value) else f"{value:.0f}"
    return str(value)


def format_table(title: str, columns, rows) -> str:
    cells = [[_format_cell(v) for v in row] for row in rows]
    widths = [
        max([len(str(col))] + [len(r[i]) for r in cells]) for i, col in enumerate(columns)
    ]
    lines = [title, "  ".join(str(c).ljust(w) for c, w in zip(columns, widths))]
    lines.append("  ".join("-" * w for w in widths))
    for row in cells:
        lines.append("  ".join(v.ljust(w) for v, w in zip(row, widths)))
    return "\n".join(lines)


def format_result(run: dict) -> str:
    result = run.get("result") or {}
    out = [
        f"experiment {run['id']} ({run['kind']}): {run['status']}",
        f"params: {json.dumps(run.get('params', {}))}",
        "",
        result.get("summary", run.get("error") or "(no result)"),
        "",
    ]
    metrics: Dict[str, float] = result.get("metrics") or {}
    if metrics:
        out.append("metrics:")
        for key, value in metrics.items():
            out.append(f"  {key:<32} {_format_cell(value)}")
        out.append("")
    for tbl in result.get("tables") or []:
        out.append(format_table(tbl["title"], tbl["columns"], tbl["rows"]))
        out.append("")
    return "\n".join(out)


def cmd_experiment_list(_args: argparse.Namespace) -> int:
    for spec in list_specs():
        print(f"{spec.name:<22} {spec.title} — {spec.report_section} [{spec.estimated}]")
        print(f"{'':<22} {spec.description}")
        for p in spec.params:
            bounds = ""
            if p.min is not None or p.max is not None:
                bounds = f" [{p.min}..{p.max}]"
            if p.choices:
                bounds = f" {{{', '.join(p.choices)}}}"
            print(f"{'':<24} --param {p.name}={p.default!r}{bounds}  {p.description}")
        print()
    return 0


def cmd_experiment_run(args: argparse.Namespace) -> int:
    from tiles.ledger.store import Ledger

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(str(db_path))
    params = dict(args.param)

    def on_event(_run_id: str, event: dict) -> None:
        if event["type"] == "progress":
            total = event.get("total") or 0
            print(
                f"\r  [{event['done']}/{total}] {event.get('message', '')[:70]:<70}",
                end="",
                file=sys.stderr,
                flush=True,
            )
        elif event["type"] == "log":
            print(f"\n  {event.get('level', 'info')}: {event.get('message', '')}", file=sys.stderr)

    manager = ExperimentManager(ledger, on_event=on_event)
    try:
        run = manager.run_sync(args.kind, params)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        print(file=sys.stderr)
    print(format_result(run))
    if args.output:
        with open(args.output, "w") as fh:
            json.dump(run, fh, indent=2, default=str)
        print(f"wrote {args.output}")
    ledger.close()
    return 0 if run["status"] == "completed" else 1


def add_experiment_commands(subparsers) -> None:
    parser = subparsers.add_parser(
        "experiment", help="run or list the report's experiments"
    )
    sub = parser.add_subparsers(dest="experiment_command", required=True)

    p = sub.add_parser("list", help="list experiment kinds and their parameters")
    p.set_defaults(func=cmd_experiment_list)

    p = sub.add_parser("run", help="run one experiment to completion")
    p.add_argument("kind", help="experiment kind (see `tiles experiment list`)")
    p.add_argument(
        "--param",
        action="append",
        default=[],
        type=_parse_param,
        metavar="KEY=VALUE",
        help="override a parameter (repeatable)",
    )
    p.add_argument("--db", default=DEFAULT_DB, help="ledger to record into")
    p.add_argument("--output", default=None, help="also write the run as JSON")
    p.set_defaults(func=cmd_experiment_run)
