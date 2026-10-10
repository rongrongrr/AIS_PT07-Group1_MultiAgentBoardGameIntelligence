"""TILES Play Engine: live play on buddyboardgames.com.

Pure-python pieces (``protocol``, ``state_translator``) are always
importable; ``BrowserSeat``/``LiveSession`` additionally need Playwright
(``pip install 'tiles[live]' && playwright install chromium``).
"""

from .protocol import DEFAULT_PLATFORM_URL, parse_socketio_frame
from .state_translator import (
    action_to_site_moves,
    infer_action,
    site_state_to_game_state,
)

__all__ = [
    "DEFAULT_PLATFORM_URL",
    "parse_socketio_frame",
    "action_to_site_moves",
    "infer_action",
    "site_state_to_game_state",
    "BrowserSeat",
    "LiveSeat",
    "LiveSession",
    "LiveSessionConfig",
]


def __getattr__(name):  # lazy: keep Playwright optional
    if name in ("BrowserSeat",):
        from .browser_seat import BrowserSeat

        return BrowserSeat
    if name in ("LiveSeat", "LiveSession", "LiveSessionConfig"):
        from . import live_session

        return getattr(live_session, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
