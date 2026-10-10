"""Shared server state.

One ``AppState`` instance hangs off ``app.state.tiles``; routers reach
it through ``request.app.state.tiles`` (or ``websocket.app.state.tiles``)
so every router module stays importable and testable on its own.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from tiles.ledger.store import Ledger

if TYPE_CHECKING:  # pragma: no cover
    from tiles.experiments.runner import ExperimentManager
    from tiles.server.sessions import SessionManager

VERSION = "0.3.0"


def live_available() -> bool:
    """True when Playwright is importable (live play possible)."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@dataclass
class AppState:
    ledger: Ledger
    sessions: "SessionManager"
    experiments: "ExperimentManager"
    #: the running event loop, captured at startup; worker threads use it
    #: to fan events out to WebSocket subscribers.
    loop: Optional[asyncio.AbstractEventLoop] = None
