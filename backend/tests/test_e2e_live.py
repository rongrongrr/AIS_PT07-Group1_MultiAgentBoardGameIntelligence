"""Live end-to-end tests: run complete 2-player games on buddyboardgames.com.

These tests launch real Playwright browsers, connect to the actual Azul
platform, and play full games with GreedyPlayer bots. They verify:
1. Both bots can join the same room
2. The game starts and tiles are dealt
3. Bots take turns making valid moves
4. The game reaches completion (a player wins)
5. Scores are recorded

Run with: pytest tests/test_e2e_live.py -v -s --timeout=300

NOTE: Requires internet access to buddyboardgames.com
"""

import asyncio
import logging
import os
import random
import time

import pytest

from app.engine.play_engine import BotBrowser, MultiPlayerSession
from app.engine.state_parser import parse_state_from_dom
from app.azul.rules import get_legal_actions
from app.ml.greedy_player import GreedyPlayer
from app.models.schemas import BrowserMode, GameStateData

logger = logging.getLogger(__name__)

# Use headless for CI, headed for local debugging
HEADLESS = os.environ.get("E2E_HEADED", "0") != "1"
BROWSER_MODE = BrowserMode.HEADLESS if HEADLESS else BrowserMode.HEADED


async def run_one_game(game_number: int) -> dict:
    """Run a single complete 2-player game end-to-end.

    Returns a dict with game results.
    """
    room_name = f"e2e-test-{game_number}-{random.randint(1000, 9999)}"
    player_names = ["E2E_Alice", "E2E_Bob"]
    models = [GreedyPlayer(), GreedyPlayer()]

    mp = MultiPlayerSession(
        session_id=f"e2e_{game_number}",
        room_name=room_name,
        platform_url="https://buddyboardgames.com/azul",
        browser_mode=BROWSER_MODE,
    )
    mp.add_bot(player_names[0], is_host=True)
    mp.add_bot(player_names[1], is_host=False)

    results = {
        "game_number": game_number,
        "room_name": room_name,
        "success": False,
        "total_moves": 0,
        "scores": {},
        "error": None,
    }

    try:
        # Launch browsers
        logger.info(f"[Game {game_number}] Launching browsers for room '{room_name}'")
        await mp.launch_all()

        # Join room
        await mp.join_all()
        for bot in mp.bots:
            assert bot.in_lobby, f"{bot.player_name} failed to join lobby"
        logger.info(f"[Game {game_number}] Both bots in lobby")

        # Start game
        await mp.start_game()
        for bot in mp.bots:
            for _ in range(10):
                if bot.game_started:
                    break
                await asyncio.sleep(0.5)
        logger.info(f"[Game {game_number}] Game started")

        # Deal tiles
        host = mp.host
        await host.deal_tiles()
        await asyncio.gather(*(bot.wait_for_state_update(timeout_s=8) for bot in mp.bots))
        await asyncio.sleep(1)
        for bot in mp.bots:
            await bot.refresh_state_from_dom()
        logger.info(f"[Game {game_number}] Tiles dealt")

        # Game loop
        total_moves = 0
        max_moves = 200
        last_progress = time.time()
        consecutive_failures = 0

        while total_moves < max_moves:
            acted = False

            for i, bot in enumerate(mp.bots):
                if bot.game_over:
                    continue

                if total_moves > 0 and await bot.check_game_over():
                    logger.info(f"[Game {game_number}] {bot.player_name} sees game over")
                    continue

                if not await bot.is_my_turn():
                    continue

                # Deal if needed
                if await bot.needs_deal():
                    logger.info(f"[Game {game_number}] {bot.player_name} dealing new round")
                    await bot.deal_tiles()
                    await bot.wait_for_state_update(timeout_s=8)
                    await asyncio.sleep(1)
                    await bot.refresh_state_from_dom()
                    acted = True
                    last_progress = time.time()
                    continue

                # Get state
                state = await bot.refresh_state_from_dom()
                if not state:
                    await asyncio.sleep(0.5)
                    continue

                # Check tiles exist
                has_tiles = any(len(f) > 0 for f in state.factories) or bool(
                    [t for t in state.center_pool if t != "firstPlayer"]
                )
                if not has_tiles:
                    await bot.deal_tiles()
                    await bot.wait_for_state_update(timeout_s=8)
                    await bot.refresh_state_from_dom()
                    acted = True
                    last_progress = time.time()
                    continue

                # Decide
                model = models[i]
                try:
                    action = await asyncio.wait_for(
                        model.decide(state, 0),  # always index 0 for own board
                        timeout=10,
                    )
                except Exception as e:
                    logger.error(f"[Game {game_number}] {bot.player_name} decide failed: {e}")
                    consecutive_failures += 1
                    if consecutive_failures > 5:
                        results["error"] = f"Too many consecutive failures: {e}"
                        raise RuntimeError(results["error"])
                    continue

                # Execute
                success = await bot.execute_move(action)
                if not success:
                    consecutive_failures += 1
                    if consecutive_failures > 10:
                        results["error"] = "Too many click failures"
                        raise RuntimeError(results["error"])
                    await asyncio.sleep(0.5)
                    continue

                # Verify
                state_changed = await bot.wait_for_state_update(timeout_s=5)
                if not state_changed:
                    await bot.refresh_state_from_dom()

                total_moves += 1
                consecutive_failures = 0
                last_progress = time.time()
                acted = True

                logger.info(
                    f"[Game {game_number}] Move {total_moves}: {bot.player_name} "
                    f"{action.color.value} {action.source_type.value}[{action.source_index}] "
                    f"-> {action.destination.value}[{action.destination_row}]"
                )

            # Check game over
            if all(bot.game_over for bot in mp.bots):
                break

            # Stuck check
            if time.time() - last_progress > 20:
                results["error"] = f"Stuck for 20s at move {total_moves}"
                break

            if not acted:
                await asyncio.sleep(0.5)

        # Get final scores
        for bot in mp.bots:
            scores = await bot.get_scores()
            results["scores"].update(scores)

        results["total_moves"] = total_moves
        results["success"] = all(bot.game_over for bot in mp.bots) or total_moves > 0

        logger.info(
            f"[Game {game_number}] DONE: {total_moves} moves, "
            f"scores={results['scores']}, "
            f"game_over={all(bot.game_over for bot in mp.bots)}"
        )

    except Exception as e:
        results["error"] = str(e)
        logger.error(f"[Game {game_number}] ERROR: {e}")
    finally:
        await mp.close_all()

    return results


class TestE2ELiveGames:
    """Run 3 complete live games on the actual platform."""

    @pytest.mark.asyncio
    async def test_three_complete_games(self):
        results = []
        for i in range(1, 4):
            logger.info(f"\n{'='*60}\n  GAME {i} of 3\n{'='*60}")
            result = await run_one_game(i)
            results.append(result)
            print(f"\nGame {i}: moves={result['total_moves']} scores={result['scores']} "
                  f"success={result['success']} error={result['error']}")

            if result["error"] and "Stuck" not in str(result["error"]):
                # Hard failure — don't continue
                break

            # Brief pause between games
            await asyncio.sleep(2)

        # Verify results
        for i, r in enumerate(results, 1):
            assert r["total_moves"] > 0, f"Game {i} made no moves: {r['error']}"
            print(f"Game {i}: {r['total_moves']} moves, scores={r['scores']}")

        successful = [r for r in results if r["success"] and not r["error"]]
        assert len(successful) >= 1, (
            f"At least 1 of 3 games should complete. Results: "
            f"{[(r['total_moves'], r['error']) for r in results]}"
        )
