"""Input validation for session configuration and external model URLs."""

from __future__ import annotations

import ipaddress
import os
import re
from typing import Iterable, List, Optional
from urllib.parse import urlparse

DEFAULT_PLATFORM_HOSTS = "buddyboardgames.com,www.buddyboardgames.com,localhost,127.0.0.1"
NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]+$")          # what we are willing to type into the platform
ROOM_RE = re.compile(r"^[A-Za-z0-9 _.\-]+$")


def allowed_platform_hosts() -> set:
    raw = os.environ.get("TILES_ALLOWED_PLATFORM_HOSTS", DEFAULT_PLATFORM_HOSTS)
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def check_platform_url(url: str) -> Optional[str]:
    """Error message if the browser may not be pointed at ``url``, else None.

    The bots drive a real browser to this URL, so an arbitrary value would let an API caller make the
    server visit any host. Only the hosts in ``TILES_ALLOWED_PLATFORM_HOSTS`` are accepted.
    """
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed_platform_hosts():
        return f"platform_url host '{host}' is not allowed (allowed: {sorted(allowed_platform_hosts())})"
    return None


def check_remote_model_url(url: str) -> Optional[str]:
    """Error message for URLs a remote model must not use (cloud metadata / link-local addresses)."""
    host = urlparse(url).hostname or ""
    if not host:
        return "url has no host"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "link-local hostnames are not allowed" if host.lower() in {"metadata.google.internal"} else None
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return f"address {host} is not allowed for a remote model"
    return None


def check_session_players(players: Iterable, known_types: Iterable[str], default_name=None) -> List[str]:
    """All problems with a session's player list (empty list = valid)."""
    players = list(players)
    known = set(known_types)
    problems: List[str] = []
    if not 2 <= len(players) <= 4:
        problems.append("a session needs 2 to 4 players")
    slots = [p.slot for p in players]
    if len(set(slots)) != len(slots):
        problems.append("slot numbers must be unique")
    if players and all(p.type == "human" for p in players):
        problems.append("at least one machine player is required (the host browser is a bot)")
    names = []
    for p in players:
        if p.type != "human" and p.type not in known:
            problems.append(f"unknown player type '{p.type}'")
        name = (p.name or (default_name(p) if default_name else "")).strip()
        if not name:
            problems.append(f"slot {p.slot} has no name")
        elif not NAME_RE.match(name):
            problems.append(f"player name '{name}' may only contain letters, digits, space, '_', '.' and '-'")
        names.append(name.lower())
    if len(set(names)) != len(names):
        problems.append("player names must be unique (case-insensitive)")
    return problems
