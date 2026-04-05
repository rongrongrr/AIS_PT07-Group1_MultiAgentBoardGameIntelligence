#!/usr/bin/env python3
"""Diagnostic script: run one complete 2-player game with detailed step-by-step logging.

Usage: cd backend && source venv/bin/activate && python test_single_game.py
"""

import asyncio
import json
import random
import sys
import time
from base64 import b64encode
from datetime import datetime

from playwright.async_api import async_playwright

# Add app to path
sys.path.insert(0, ".")

from app.engine.state_parser import parse_socketio_message, parse_game_state_from_event, parse_state_from_dom
from app.engine.action_executor import execute_action
from app.azul.rules import get_legal_actions
from app.ml.greedy_player import GreedyPlayer
from app.models.schemas import BrowserMode, TileColor


def log(phase, msg, data=None):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    prefix = f"[{ts}] [{phase:12s}]"
    print(f"{prefix} {msg}")
    if data:
        for k, v in data.items():
            print(f"{'':>28s} {k}: {v}")


INIT_SCRIPT = """(function() {
    let _io;
    try {
        Object.defineProperty(window, 'io', {
            configurable: true,
            get() { return _io; },
            set(val) {
                _io = val;
                if (val && typeof val.connect === 'function') {
                    const orig = val.connect.bind(val);
                    val.connect = function() {
                        const s = orig.apply(val, arguments);
                        window.__oppo_socket = s;
                        return s;
                    };
                }
            }
        });
    } catch(e) {}
})();"""


async def launch_bot(name, room, is_host):
    """Launch a single bot browser and join the room."""
    log("launch", f"Starting browser for {name} (host={is_host})")
    t0 = time.time()

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()

    # Track WS frames
    ws_frames = []
    def on_ws(ws):
        ws.on("framereceived", lambda d: ws_frames.append(("recv", d)))
        ws.on("framesent", lambda d: ws_frames.append(("sent", d)))
    page.on("websocket", on_ws)

    await page.add_init_script(INIT_SCRIPT)

    name_b64 = b64encode(name.encode()).decode()
    await page.goto(f"https://buddyboardgames.com/azul?name={name_b64}", wait_until="networkidle")
    await page.wait_for_timeout(1000)

    launch_ms = int((time.time() - t0) * 1000)
    log("launch", f"{name} browser ready in {launch_ms}ms")

    # Join room
    t0 = time.time()
    await page.fill("#room", room)
    await page.wait_for_timeout(200)
    await page.click("#start-game")
    await page.wait_for_timeout(2500)

    in_lobby = await page.evaluate("""() => {
        const el = document.querySelector('#sharing-link-row');
        return !!(el && !el.classList.contains('d-none'));
    }""") or False

    # Store room/player on window for Socket.IO emits
    await page.evaluate(
        """([room, player]) => {
            window.__oppo_room = room;
            window.__oppo_player = player;
        }""",
        [room, name],
    )

    join_ms = int((time.time() - t0) * 1000)
    log("join", f"{name} joined room '{room}' in {join_ms}ms (in_lobby={in_lobby})")

    # Check socket
    has_socket = await page.evaluate("() => !!window.__oppo_socket") or False
    socket_connected = await page.evaluate(
        "() => window.__oppo_socket ? window.__oppo_socket.connected : false"
    ) or False
    log("socket", f"{name} socket: exists={has_socket} connected={socket_connected}")

    return {
        "name": name,
        "pw": pw,
        "browser": browser,
        "page": page,
        "ws_frames": ws_frames,
        "is_host": is_host,
    }


async def start_game(host_bot):
    """Host clicks Start Game."""
    page = host_bot["page"]
    name = host_bot["name"]

    t0 = time.time()
    btn = await page.query_selector("#start-game-lobby")
    if not btn:
        log("start", f"{name} ERROR: Start button not found")
        return False

    disabled = await btn.get_attribute("disabled")
    log("start", f"{name} Start button found (disabled={disabled})")

    if not disabled:
        await btn.click()
        await page.wait_for_timeout(2000)
        start_ms = int((time.time() - t0) * 1000)
        log("start", f"{name} Game started in {start_ms}ms")
        return True
    return False


async def deal_tiles(bot):
    """Emit dealTiles via socket."""
    page = bot["page"]
    name = bot["name"]
    room = await page.evaluate("() => document.querySelector('#azul-room-name-text')?.textContent?.trim() || ''") or ""

    t0 = time.time()
    result = await page.evaluate(
        """([room, player]) => {
            const socket = window.__oppo_socket;
            if (socket && typeof socket.emit === 'function') {
                socket.emit('takeTurn', {
                    room: room, player: player,
                    gameName: 'azul', turnType: 'dealTiles'
                });
                return true;
            }
            return false;
        }""",
        [room or bot.get("room", ""), name],
    )
    await page.wait_for_timeout(2000)
    deal_ms = int((time.time() - t0) * 1000)
    log("deal", f"{name} dealTiles emitted={result} in {deal_ms}ms (room='{room}')")
    return result


async def read_state(bot):
    """Read game state from DOM."""
    page = bot["page"]
    name = bot["name"]

    t0 = time.time()
    state = await parse_state_from_dom(page)
    dom_ms = int((time.time() - t0) * 1000)

    if not state:
        log("state", f"{name} DOM parse FAILED ({dom_ms}ms)")
        return None

    factory_tiles = sum(len(f) for f in state.factories)
    center_tiles = len([t for t in state.center_pool if t != "firstPlayer"])
    log("state", f"{name} DOM parsed in {dom_ms}ms", {
        "factories": len(state.factories),
        "factory_tiles": factory_tiles,
        "center_tiles": center_tiles,
        "players": len(state.players),
        "player_scores": {p.name: p.score for p in state.players},
    })
    return state


async def is_my_turn(bot):
    """Check if it's this bot's turn using prompt text — most reliable."""
    page = bot["page"]
    result = await page.evaluate("""() => {
        const lobby = document.querySelector('#sharing-link-row');
        if (lobby && !lobby.classList.contains('d-none')) return false;
        const modal = document.querySelector('#new-game-modal');
        if (modal && modal.classList.contains('show')) return false;
        const text = document.body.innerText;
        if (text.includes('Select a tile to claim')) return true;
        if (text.includes('Waiting for')) return false;
        // Don't use CSS class — unreliable
        return false;
    }""") or False
    return result


async def check_game_over(bot):
    """Check game over."""
    page = bot["page"]
    return await page.evaluate("""() => {
        const rematch = document.querySelector('.rematch-button');
        if (rematch && rematch.offsetHeight > 0) return true;
        const pyro = document.querySelector('.pyro');
        if (pyro && pyro.offsetHeight > 0) return true;
        return false;
    }""") or False


async def do_move(bot, state, model):
    """Make one move: decide + click + verify."""
    page = bot["page"]
    name = bot["name"]

    # Decide
    t0 = time.time()
    legal = get_legal_actions(state, 0)  # always index 0 for own browser
    log("decide", f"{name} has {len(legal)} legal actions")

    if not legal:
        log("decide", f"{name} ERROR: No legal actions!")
        return False, "no_legal_actions"

    action = await model.decide(state, 0)
    decide_ms = int((time.time() - t0) * 1000)
    log("decide", f"{name} chose in {decide_ms}ms", {
        "color": action.color.value,
        "source": f"{action.source_type.value}[{action.source_index}]",
        "dest": f"{action.destination.value}[{action.destination_row}]",
    })

    # Verify the tile exists in DOM before clicking
    if action.source_type.value == "factory":
        selector = f"#factory-{action.source_index} .tile[tilecolor='{action.color.value}']"
    else:
        selector = f"#center-row .tile[tilecolor='{action.color.value}']"

    tile_count = await page.locator(selector).count()
    log("verify", f"{name} tile selector '{selector}' -> count={tile_count}")

    if tile_count == 0:
        # Debug: dump what's actually in that factory
        if action.source_type.value == "factory":
            actual = await page.evaluate(f"""() => {{
                const f = document.querySelector('#factory-{action.source_index}');
                if (!f) return 'factory not found';
                const tiles = f.querySelectorAll('.tile');
                return Array.from(tiles).map(t => t.getAttribute('tilecolor'));
            }}""")
            log("verify", f"{name} Factory {action.source_index} actual tiles: {actual}")
        return False, "tile_not_found"

    # Execute click
    t0 = time.time()
    success = await execute_action(page, action, 0)
    click_ms = int((time.time() - t0) * 1000)
    log("click", f"{name} execute_action={success} in {click_ms}ms")

    if not success:
        return False, "click_failed"

    # Wait and verify state changed
    await page.wait_for_timeout(1500)
    new_state = await read_state(bot)

    return True, "ok"


async def run_game():
    room = f"diag-{random.randint(1000, 9999)}"
    model = GreedyPlayer()

    log("==========", f"Starting game in room '{room}'")
    log("==========", "="*50)

    # Launch both bots
    alice = await launch_bot("Alice", room, is_host=True)
    alice["room"] = room
    bob = await launch_bot("Bob", room, is_host=False)
    bob["room"] = room

    bots = [alice, bob]

    try:
        # Start game — the platform auto-deals tiles after startGame
        await start_game(alice)
        await asyncio.sleep(4)  # Wait for auto-deal + animation

        # Read initial state from both
        for bot in bots:
            await read_state(bot)

        # Game loop
        total_moves = 0
        max_moves = 150

        for turn_num in range(max_moves):
            # Check if round ended — no tiles and nobody's turn
            host = bots[0]
            state_check = await read_state(host)
            if state_check:
                ft = sum(len(f) for f in state_check.factories)
                ct = len([t for t in state_check.center_pool if t != "firstPlayer"])
                if ft == 0 and ct == 0 and not await is_my_turn(host):
                    log("round_end", f"Round ended (0 tiles). Waiting for scoring...")
                    await asyncio.sleep(4)
                    # Try dealing
                    log("round_end", f"Dealing tiles for new round")
                    await deal_tiles(host)
                    await asyncio.sleep(3)
                    for bot in bots:
                        await read_state(bot)
                    continue

            log("----------", f"Turn loop iteration {turn_num}")

            for bot in bots:
                name = bot["name"]

                # Check game over
                if await check_game_over(bot):
                    log("GAME_OVER", f"{name} sees game over after {total_moves} moves!")
                    scores = await bot["page"].evaluate("""() => {
                        const scores = {};
                        for (let i = 0; i < 4; i++) {
                            const el = document.querySelector(`#player-${i}-score`);
                            if (!el) break;
                            const nameEl = i === 0
                                ? document.querySelector('#me-info-name')
                                : document.querySelectorAll('.other-player-info-text b')[i-1];
                            const n = nameEl ? nameEl.textContent.trim() : `P${i}`;
                            scores[n] = parseInt(el.textContent) || 0;
                        }
                        return scores;
                    }""") or {}
                    log("GAME_OVER", f"Final scores: {scores}")
                    return {"moves": total_moves, "scores": scores, "success": True}

                # Check turn
                my_turn = await is_my_turn(bot)
                if not my_turn:
                    continue

                log("turn", f"It's {name}'s turn (move #{total_moves + 1})")

                # Check if need to deal
                state = await read_state(bot)
                if not state:
                    continue

                factory_tiles = sum(len(f) for f in state.factories)
                center_tiles = len([t for t in state.center_pool if t != "firstPlayer"])

                if factory_tiles == 0 and center_tiles == 0:
                    # Round is over — wait for scoring animation, then deal
                    log("deal", f"{name} round ended (no tiles), waiting for scoring...")
                    await asyncio.sleep(3)  # scoring animation
                    log("deal", f"{name} dealing tiles for new round")
                    await deal_tiles(bot)
                    await asyncio.sleep(3)
                    state = await read_state(bot)
                    if not state:
                        continue
                    factory_tiles = sum(len(f) for f in state.factories)
                    if factory_tiles == 0:
                        log("deal", f"{name} WARNING: still no tiles after deal!")
                        # The platform may auto-deal, wait more
                        await asyncio.sleep(3)
                        state = await read_state(bot)
                        if state:
                            factory_tiles = sum(len(f) for f in state.factories)
                            log("deal", f"{name} tiles after extra wait: {factory_tiles}")
                        continue

                # Try up to 3 different actions if first is rejected
                move_success = False
                for attempt in range(3):
                    success, reason = await do_move(bot, state, model)
                    if success:
                        total_moves += 1
                        await asyncio.sleep(1.5)
                        new_state = await read_state(bot)
                        if new_state:
                            new_ftiles = sum(len(f) for f in new_state.factories)
                            new_ctiles = len([t for t in new_state.center_pool if t != "firstPlayer"])
                            log("move_ok", f"{name} move #{total_moves} succeeded "
                                f"(tiles: {factory_tiles}+{center_tiles} -> {new_ftiles}+{new_ctiles})")
                        else:
                            log("move_ok", f"{name} move #{total_moves} succeeded")
                        move_success = True
                        break
                    else:
                        log("move_fail", f"{name} attempt {attempt+1} failed: {reason}")
                        # Refresh state and try a different action
                        await asyncio.sleep(1)
                        state = await read_state(bot)
                        if not state:
                            break
                if not move_success:
                    log("move_fail", f"{name} all 3 attempts failed, skipping")

        log("timeout", f"Game did not finish after {total_moves} moves")
        return {"moves": total_moves, "scores": {}, "success": False, "reason": "max_moves"}

    finally:
        for bot in bots:
            try:
                await bot["page"].close()
                await bot["browser"].close()
                await bot["pw"].stop()
            except:
                pass
        log("cleanup", "All browsers closed")


async def main():
    print("\n" + "="*60)
    print("  OPPO PROFILE - LIVE GAME DIAGNOSTIC")
    print("="*60 + "\n")

    result = await run_game()
    print("\n" + "="*60)
    print(f"  RESULT: {json.dumps(result, indent=2)}")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
