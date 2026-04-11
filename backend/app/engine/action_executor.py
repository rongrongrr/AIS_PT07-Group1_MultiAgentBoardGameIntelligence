"""Execute Azul game actions via Socket.IO emits through the browser."""

from __future__ import annotations

import logging

from app.models.schemas import DestinationType, GameAction, SourceType

logger = logging.getLogger(__name__)


async def execute_action(page, action: GameAction, player_index: int = 0) -> bool:
    """Execute a GameAction by emitting Socket.IO chooseTiles + placeTiles.

    Returns True only if BOTH steps succeed on the server.
    """
    try:
        # Step 1: chooseTiles
        choose = _build_choose_payload(action)
        result = await _emit_and_wait(page, choose)
        if not result["ok"]:
            logger.error(f"chooseTiles REJECTED: {result['msg']} | "
                         f"{action.color.value} from {action.source_type.value}[{action.source_index}]")
            return False
        logger.info(f"chooseTiles OK: {action.color.value} from "
                     f"{action.source_type.value}[{action.source_index}]")

        await page.wait_for_timeout(300)

        # Step 2: placeTiles
        place = _build_place_payload(action)
        result = await _emit_and_wait(page, place)
        if not result["ok"]:
            logger.warning(f"placeTiles rejected: {result['msg']} | "
                           f"-> {action.destination.value}[{action.destination_row}], trying floor fallback")
            # Fallback: place on floor if pattern line was rejected
            floor_payload = {"turnType": "placeTiles", "floorLine": True}
            result = await _emit_and_wait(page, floor_payload)
            if not result["ok"]:
                logger.error(f"placeTiles floor fallback also REJECTED: {result['msg']}")
                return False
            logger.info("placeTiles OK: floor (fallback)")
        else:
            logger.info(f"placeTiles OK: -> {action.destination.value}[{action.destination_row}]")

        await page.wait_for_timeout(800)
        return True

    except Exception as e:
        logger.error(f"Action execution error: {e}", exc_info=True)
        return False


async def _emit_and_wait(page, payload: dict) -> dict:
    """Emit a takeTurn event and wait for the server's takeTurnResponse.

    Uses a non-consuming listener (on + off) instead of socket.once, so that
    the platform's own client JS and our WebSocket frame handler still receive
    the event.
    """
    return await page.evaluate(
        """(payload) => {
            return new Promise((resolve) => {
                const socket = window.__tiles_socket;
                if (!socket) { resolve({ok: false, msg: 'no_socket'}); return; }

                const room = window.__tiles_room || '';
                const player = window.__tiles_player || '';
                if (!room || !player) {
                    resolve({ok: false, msg: 'no_room=[' + room + '] player=[' + player + ']'});
                    return;
                }

                payload.room = room;
                payload.player = player;
                payload.gameName = 'azul';

                // Store the last response globally so it doesn't consume the event
                let resolved = false;
                const handler = (resp) => {
                    if (!resolved) {
                        resolved = true;
                        socket.off('takeTurnResponse', handler);
                        resolve({ok: !!resp.success, msg: resp.message || ''});
                    }
                };
                // Use 'on' not 'once' — we manually remove after first call
                // This allows the platform's own handlers to still fire
                socket.prependOnceListener
                    ? socket.prependOnceListener('takeTurnResponse', handler)
                    : socket.once('takeTurnResponse', handler);

                socket.emit('takeTurn', payload);

                setTimeout(() => {
                    if (!resolved) {
                        resolved = true;
                        socket.off('takeTurnResponse', handler);
                        resolve({ok: false, msg: 'timeout_5s'});
                    }
                }, 5000);
            });
        }""",
        payload,
    )


def _build_choose_payload(action: GameAction) -> dict:
    payload = {"turnType": "chooseTiles", "tileType": action.color.value}
    if action.source_type == SourceType.FACTORY:
        payload["factory"] = str(action.source_index)
    elif action.source_type == SourceType.CENTER:
        payload["center"] = True
    return payload


def _build_place_payload(action: GameAction) -> dict:
    payload = {"turnType": "placeTiles"}
    if action.destination == DestinationType.PATTERN_LINE:
        payload["patternLine"] = str(action.destination_row)
    elif action.destination == DestinationType.FLOOR:
        payload["floorLine"] = True
    return payload
