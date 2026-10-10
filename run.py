#!/usr/bin/env python3
"""TILES launcher: the single entry point for running the application.

    python run.py              # dev: API + hot-reload web app (default)
    python run.py app          # one process: built web app served by the API
    python run.py docker       # the same app in a container (Docker Compose)
    python run.py docker --live    # container with Chromium, for live play

Use the platform wrapper rather than calling this file directly if you
prefer: ``./start.sh`` on macOS and Linux, ``start.cmd`` on Windows. Both
only find Python 3.10+ and pass their arguments through to this script.

Only the standard library is used here, so it runs on a bare Python
install. On first run it creates ``backend/.venv``, installs the backend
and the frontend packages, and downloads Chromium for live play; later
runs reuse them and reinstall only when ``pyproject.toml`` or
``package-lock.json`` has changed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, NoReturn, Optional

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"
WINDOWS = os.name == "nt"
#: Every child started by spawn(); stopped on any exit (see main()).
CHILDREN: List[subprocess.Popen] = []
EXTRAS = "dev,rl,live,llm"
MIN_PYTHON = (3, 10)


def say(message: str) -> None:
    print(f"[tiles] {message}", flush=True)


def fail(message: str) -> NoReturn:
    print(f"[tiles] error: {message}", file=sys.stderr, flush=True)
    sys.exit(1)


# -- tools --------------------------------------------------------------------


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def require_tool(name: str, hint: str) -> str:
    path = shutil.which(name)  # resolves npm.cmd / docker.exe on Windows
    if path is None:
        fail(f"'{name}' was not found on PATH. {hint}")
    return path


def run(cmd: List[str], cwd: Optional[Path] = None) -> None:
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        fail(f"command failed ({result.returncode}): {' '.join(map(str, cmd))}")


def digest(*paths: Path) -> str:
    h = hashlib.sha256()
    for path in paths:
        h.update(path.read_bytes() if path.exists() else b"")
    return h.hexdigest()


# -- setup --------------------------------------------------------------------


def ensure_backend(live: bool) -> Path:
    """Create or refresh backend/.venv; returns its Python."""
    python = venv_python()
    healthy = python.exists() and subprocess.run(
        [str(python), "-c", "import tiles, fastapi, uvicorn"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not healthy:
        say("creating the backend environment (backend/.venv)…")
        shutil.rmtree(VENV, ignore_errors=True)
        run([sys.executable, "-m", "venv", str(VENV)])

    stamp = VENV / ".tiles-install"
    wanted = digest(BACKEND / "pyproject.toml") + EXTRAS
    if not healthy or not stamp.exists() or stamp.read_text() != wanted:
        say("installing the backend (first run, or its dependencies changed)…")
        run([str(python), "-m", "pip", "install", "-q", "-e", f"{BACKEND}[{EXTRAS}]"])
        stamp.write_text(wanted)

    if live:
        # Idempotent and quick once Chromium is present.
        result = subprocess.run(
            [str(python), "-m", "playwright", "install", "chromium"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            say("warning: Chromium could not be installed; live play will be unavailable.")
    return python


def ensure_frontend(npm: str) -> None:
    stamp = FRONTEND / "node_modules" / ".tiles-install"
    wanted = digest(FRONTEND / "package.json", FRONTEND / "package-lock.json")
    if not stamp.exists() or stamp.read_text() != wanted:
        say("installing the frontend packages…")
        # `ci` installs exactly what package-lock.json pins and never
        # rewrites it (`install` can, leaving a dirty working tree).
        run([npm, "ci"], cwd=FRONTEND)
        stamp.write_text(wanted)


# -- processes ----------------------------------------------------------------


def local_address(host: str) -> str:
    """Where to reach a server bound to ``host`` from this machine."""
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((local_address(host), port)) == 0


def require_port(host: str, port: int, setting: str) -> None:
    if port_in_use(host, port):
        fail(f"port {port} is already in use. Stop that process, or pass {setting} <port>.")


def spawn(cmd: List[str], cwd: Path, env: Dict[str, str]) -> subprocess.Popen:
    """Start a child in its own process group so it can be stopped as a
    whole (npm starts node, which starts esbuild)."""
    kwargs: dict = {"cwd": cwd, "env": {**os.environ, **env}}
    if WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    CHILDREN.append(proc)
    return proc


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if not WINDOWS:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def wait_healthy(url: str, proc: subprocess.Popen, timeout_s: float = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            fail("the API exited during startup (see the output above).")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    fail(f"the API did not become healthy at {url}")


def supervise(procs: List[subprocess.Popen]) -> int:
    """Run until any process exits (Ctrl+C is handled in main())."""
    while all(p.poll() is None for p in procs):
        time.sleep(0.5)
    failed = next(p for p in procs if p.poll() is not None)
    if failed.returncode:
        say(f"a process exited with code {failed.returncode}; stopping the rest.")
    return failed.returncode or 0


_received: List[int] = []


def _interrupt(signum, frame) -> None:
    _received.append(signum)
    raise KeyboardInterrupt


def handle_signals() -> None:
    """Treat termination and hang-up (closing the terminal) like Ctrl+C,
    so the servers never outlive the launcher."""
    signal.signal(signal.SIGINT, _interrupt)  # even if started with it ignored
    signal.signal(signal.SIGTERM, _interrupt)
    if not WINDOWS:
        signal.signal(signal.SIGHUP, _interrupt)


def start_api(python: Path, args: argparse.Namespace, env: Dict[str, str]) -> subprocess.Popen:
    require_port(args.host, args.api_port, "--api-port")
    say(f"starting the API at http://{args.host}:{args.api_port} …")
    api = spawn(
        [str(python), "-m", "tiles.cli", "serve", "--host", args.host, "--port", str(args.api_port)],
        cwd=BACKEND,  # the database lives in backend/db/tiles.db
        env=env,
    )
    wait_healthy(f"http://{local_address(args.host)}:{args.api_port}/api/health", api)
    return api


# -- modes --------------------------------------------------------------------


def mode_dev(args: argparse.Namespace) -> int:
    npm = require_tool("npm", "Install Node.js 18 or newer from https://nodejs.org.")
    python = ensure_backend(live=not args.no_live)
    ensure_frontend(npm)
    require_port("127.0.0.1", args.ui_port, "--ui-port")

    api = start_api(python, args, env={})
    say(f"starting the web app at http://localhost:{args.ui_port} …")
    ui = spawn(
        [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(args.ui_port), "--strictPort"],
        cwd=FRONTEND,
        env={"TILES_API_PROXY": f"http://{local_address(args.host)}:{args.api_port}"},
    )
    say(f"TILES is up: http://localhost:{args.ui_port}  (API docs: "
        f"http://localhost:{args.api_port}/docs). Ctrl+C to stop.")
    return supervise([api, ui])


def mode_app(args: argparse.Namespace) -> int:
    npm = require_tool("npm", "Install Node.js 18 or newer from https://nodejs.org.")
    python = ensure_backend(live=not args.no_live)
    ensure_frontend(npm)
    say("building the web app…")
    run([npm, "run", "build"], cwd=FRONTEND)

    api = start_api(python, args, env={"TILES_UI_DIST": str(FRONTEND / "dist")})
    say(f"TILES is up: http://localhost:{args.api_port}. Ctrl+C to stop.")
    return supervise([api])


def compose_command() -> List[str]:
    docker = require_tool("docker", "Install Docker Desktop (or Docker Engine) first.")
    if subprocess.run(
        [docker, "compose", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0:
        return [docker, "compose"]
    legacy = shutil.which("docker-compose")
    if legacy:
        return [legacy]
    fail("Docker Compose was not found. Install Docker Desktop, or the compose plugin.")


def mode_docker(args: argparse.Namespace) -> int:
    compose = compose_command()
    service = "tiles-live" if args.live else "tiles"
    cmd = compose + (["--profile", "live"] if args.live else []) + ["up", "--build", service]
    say(f"starting the {'live-play ' if args.live else ''}container at "
        f"http://localhost:{args.api_port}. Ctrl+C to stop.")
    env = {**os.environ, "TILES_API_PORT": str(args.api_port)}
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        # Ctrl+C in the terminal reaches compose directly (a second one would
        # force-kill it); a termination or hang-up is passed on so compose
        # stops the container cleanly.
        if proc.poll() is None and not WINDOWS and _received[-1:] != [signal.SIGINT]:
            proc.send_signal(signal.SIGINT)
        return proc.wait()


# -- entry point --------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    if sys.version_info < MIN_PYTHON:
        fail(f"TILES needs Python {'.'.join(map(str, MIN_PYTHON))} or newer "
             f"(this is {sys.version.split()[0]}).")

    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Start TILES. Wrappers: ./start.sh (macOS, Linux), start.cmd (Windows).",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="dev",
        choices=["dev", "app", "docker"],
        help="dev: API + hot-reload web app (default); app: one process serving "
             "the built web app; docker: run in a container",
    )
    parser.add_argument("--host", default=os.environ.get("TILES_API_HOST", "127.0.0.1"),
                        help="address the API listens on (dev/app)")
    parser.add_argument("--api-port", type=int,
                        default=int(os.environ.get("TILES_API_PORT", "8000")))
    parser.add_argument("--ui-port", type=int,
                        default=int(os.environ.get("TILES_UI_PORT", "5173")),
                        help="port of the hot-reload web app (dev)")
    parser.add_argument("--no-live", action="store_true",
                        help="skip the Chromium download for live play (dev/app)")
    parser.add_argument("--live", action="store_true",
                        help="use the container image with Chromium (docker)")
    args = parser.parse_args(argv)

    if args.live and args.mode != "docker":
        parser.error("--live applies to docker mode; dev and app support live play already")

    handle_signals()
    try:
        return {"dev": mode_dev, "app": mode_app, "docker": mode_docker}[args.mode](args)
    except KeyboardInterrupt:
        print()
        return 130
    finally:
        if any(p.poll() is None for p in CHILDREN):
            say("shutting down…")
        for proc in reversed(CHILDREN):
            stop(proc)


if __name__ == "__main__":
    sys.exit(main())
