"""Optional shared-secret authentication.

Off by default (the app is meant to run locally). Set ``TILES_API_KEY`` to require the key on every
``/api`` call except ``/api/health``: as an ``X-API-Key`` header for HTTP, or ``?api_key=`` for the
session WebSocket (browsers cannot set headers on WebSockets).
"""

from __future__ import annotations

import hmac
import os
from typing import Optional


def api_key_ok(provided: Optional[str]) -> bool:
    expected = os.environ.get("TILES_API_KEY")
    return not expected or (provided is not None and hmac.compare_digest(provided, expected))
