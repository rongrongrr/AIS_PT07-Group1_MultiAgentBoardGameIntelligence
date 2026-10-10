"""Live check of the human-slot path: a session with one bot and one *human* slot, where the human
joins from a separate browser through the room name (the same thing a person does with the room link).

    python scripts/live_human_join_check.py --api http://localhost:8080

The "human" is a separate Playwright browser (outside the session's own bots) that plays a random legal
move on its turns. It proves the host waits for an external player, starts the game once that player
has joined, hands turns back and forth between the bot and the outside client, and records the game.
It does NOT test a person's clicking or timing. Exits non-zero if the game does not complete.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tiles.azul.rules import get_legal_actions  # noqa: E402
from tiles.engine.play_engine import BotBrowser  # noqa: E402
from tiles.models.schemas import BrowserMode  # noqa: E402


def call(api: str, method: str, path: str, body=None):
    req = urllib.request.Request(api + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


async def human_loop(room: str, name: str, deadline: float, moves: list) -> None:
    human = BotBrowser("human-check", room, name, browser_mode=BrowserMode.HEADLESS, is_host=False)
    await human.launch()
    try:
        await human.join_room()
        rng = random.Random(1)
        while time.monotonic() < deadline:
            if await human.check_game_over():
                return
            if await human.is_my_turn():
                state = await human.refresh_state_from_dom()
                if state is not None and not state.game_over:
                    idx = await human.get_player_index()
                    legal = get_legal_actions(state, idx)
                    if legal:
                        result = await human.execute_move(rng.choice(legal))
                        if result:
                            moves.append(time.monotonic())
                        await asyncio.sleep(1.0)
                        continue
            await asyncio.sleep(0.5)
    finally:
        await human.close()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8080")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--bot", default="GreedyPlayer")
    a = ap.parse_args()

    room = f"human-{random.randint(1000, 9999)}"
    sess = call(a.api, "POST", "/api/sessions", {"room_name": room, "players": [
        {"slot": 0, "type": a.bot, "name": "Bot"}, {"slot": 1, "type": "human", "name": "Human"}]})
    print("session", sess["id"], "room", room)
    print(call(a.api, "POST", f"/api/sessions/{sess['id']}/start")["message"])

    moves: list = []
    deadline = time.monotonic() + a.timeout
    human_task = asyncio.create_task(human_loop(room, "Human", deadline, moves))
    status = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(5)
        status = call(a.api, "GET", f"/api/sessions/{sess['id']}")
        if status["status"] in ("completed", "aborted"):
            break
    human_task.cancel()
    try:
        await human_task
    except (asyncio.CancelledError, Exception):
        pass
    hist = call(a.api, "GET", f"/api/history/{sess['id']}")
    by = {}
    for m in hist["moves"]:
        by[m["player_name"]] = by.get(m["player_name"], 0) + 1
    print("status:", status.get("status"), "scores:", status.get("final_scores"), "winner:", status.get("winner"))
    print("moves recorded per player:", by, "| human moves played by outside client:", len(moves))
    ok = status.get("status") == "completed" and by.get("Bot", 0) > 0 and len(moves) > 0
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
