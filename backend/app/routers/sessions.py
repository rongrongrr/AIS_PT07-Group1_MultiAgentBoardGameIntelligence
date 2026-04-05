"""Session management API routes — multi-bot orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession

from app.engine.play_engine import BotBrowser, MultiPlayerSession
from app.ml.registry import registry
from app.models.db import Move, Session, get_db, GameState as GameStateModel
from app.models.schemas import (
    GameAction,
    GameStateData,
    MoveRecord,
    SessionCreate,
    SessionResponse,
    SessionStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory state
_active_sessions: Dict[str, MultiPlayerSession] = {}
_session_tasks: Dict[str, asyncio.Task] = {}
_ws_connections: Dict[str, List[WebSocket]] = {}


def _session_to_response(s: Session) -> SessionResponse:
    return SessionResponse(
        id=s.id,
        room_name=s.room_name,
        platform_url=s.platform_url,
        browser_mode=s.browser_mode,
        status=s.status,
        player_config=json.loads(s.player_config),
        profiler_config=json.loads(s.profiler_config) if s.profiler_config else None,
        move_timeout_sec=s.move_timeout_sec,
        stuck_abort_sec=s.stuck_abort_sec,
        final_scores=json.loads(s.final_scores) if s.final_scores else None,
        winner=s.winner,
        created_at=s.created_at,
        completed_at=s.completed_at,
    )


@router.post("", response_model=SessionResponse)
def create_session(req: SessionCreate, db: DBSession = Depends(get_db)):
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session = Session(
        id=session_id,
        room_name=req.room_name,
        platform_url=req.platform_url,
        browser_mode=req.browser_mode.value,
        status=SessionStatus.CREATED.value,
        player_config=json.dumps([p.model_dump() for p in req.players]),
        profiler_config=json.dumps(req.profiler.model_dump()) if req.profiler else None,
        move_timeout_sec=req.move_timeout_sec,
        stuck_abort_sec=req.stuck_abort_sec,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info(f"Created session {session_id} for room '{req.room_name}'")
    return _session_to_response(session)


@router.get("", response_model=List[SessionResponse])
def list_sessions(db: DBSession = Depends(get_db)):
    sessions = db.query(Session).order_by(Session.created_at.desc()).all()
    return [_session_to_response(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: DBSession = Depends(get_db)):
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_response(session)


@router.post("/{session_id}/start")
async def start_session(session_id: str, db: DBSession = Depends(get_db)):
    """Start a game session — launches one Playwright browser per bot player."""
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in (SessionStatus.CREATED.value, SessionStatus.LOBBY.value):
        raise HTTPException(status_code=400, detail=f"Session is already {session.status}")

    player_config = json.loads(session.player_config)
    bot_slots = [p for p in player_config if p.get("type") != "human"]
    human_slots = [p for p in player_config if p.get("type") == "human"]

    if not bot_slots:
        raise HTTPException(status_code=400, detail="At least one machine player is required")

    # Validate all bot model types exist
    bot_models = {}
    for slot in bot_slots:
        model_name = slot["type"]
        model = registry.get_player(model_name)
        if not model:
            available = [p["name"] for p in registry.list_players()]
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model_name}' not found. Available: {available}",
            )
        player_name = slot.get("name") or f"Bot_{model_name}_{slot['slot']}"
        bot_models[player_name] = model

    # Create multi-player session
    mp_session = MultiPlayerSession(
        session_id=session_id,
        room_name=session.room_name,
        platform_url=session.platform_url,
        browser_mode=session.browser_mode,
    )
    mp_session.human_count = len(human_slots)

    # Add bots — first bot is host
    first = True
    for player_name in bot_models:
        mp_session.add_bot(player_name, is_host=first)
        first = False

    _active_sessions[session_id] = mp_session

    session.status = SessionStatus.LOBBY.value
    db.commit()

    move_timeout = session.move_timeout_sec
    stuck_abort = session.stuck_abort_sec

    task = asyncio.create_task(
        _run_multi_bot_game(session_id, mp_session, bot_models, db,
                            move_timeout_sec=move_timeout, stuck_abort_sec=stuck_abort)
    )
    _session_tasks[session_id] = task

    bot_names = list(bot_models.keys())
    return {
        "status": "started",
        "session_id": session_id,
        "message": f"Launching {len(bot_names)} bot(s): {bot_names}. "
                   f"{'Waiting for ' + str(len(human_slots)) + ' human(s) to join.' if human_slots else ''}",
    }


@router.post("/{session_id}/stop")
async def stop_session(session_id: str, db: DBSession = Depends(get_db)):
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    task = _session_tasks.pop(session_id, None)
    if task:
        task.cancel()

    mp = _active_sessions.pop(session_id, None)
    if mp:
        await mp.close_all()

    session.status = SessionStatus.ABORTED.value
    session.completed_at = datetime.utcnow()
    db.commit()
    return {"status": "stopped", "session_id": session_id}


@router.websocket("/{session_id}/ws")
async def session_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    if session_id not in _ws_connections:
        _ws_connections[session_id] = []
    _ws_connections[session_id].append(websocket)

    try:
        # Send current state from any bot
        mp = _active_sessions.get(session_id)
        if mp and mp.bots:
            for bot in mp.bots:
                if bot.current_state:
                    await websocket.send_json({
                        "type": "state_update",
                        "data": bot.current_state.dict(),
                    })
                    break

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        conns = _ws_connections.get(session_id, [])
        if websocket in conns:
            conns.remove(websocket)


# ---- Multi-bot game orchestration ----

async def _run_multi_bot_game(
    session_id: str,
    mp: MultiPlayerSession,
    bot_models: Dict[str, object],
    db: DBSession,
    move_timeout_sec: int = 10,
    stuck_abort_sec: int = 3,
):
    """Orchestrate a full game with multiple bots, each in their own browser."""
    step_counter = 0
    abort_reason = ""

    try:
        # 1. Launch all browsers in parallel
        logger.info(f"[{session_id}] Launching {len(mp.bots)} browser(s)...")
        await mp.launch_all()

        # 2. Join room: host first, then others
        await mp.join_all()
        _update_db_status(session_id, SessionStatus.LOBBY, db)
        logger.info(f"[{session_id}] All bots in lobby")

        # 3. Wait for human players if any
        if mp.human_count > 0:
            await mp.wait_for_humans(timeout_s=300)

        # 4. Host starts the game
        await mp.start_game()
        for bot in mp.bots:
            for _ in range(10):
                if bot.game_started:
                    break
                await asyncio.sleep(0.5)

        _update_db_status(session_id, SessionStatus.PLAYING, db)
        logger.info(f"[{session_id}] Game started ({len(mp.bots)} bots + {mp.human_count} humans, "
                     f"move_timeout={move_timeout_sec}s, stuck_abort={stuck_abort_sec}s)")

        # 5. Wait for tiles — the platform auto-deals after startGame.
        # The first player's client emits dealTiles automatically.
        # Just wait for the state to arrive and tiles to render.
        logger.info(f"[{session_id}] Waiting for initial tiles to be dealt by platform...")
        await asyncio.sleep(3)

        # Refresh state from DOM for all bots
        for bot in mp.bots:
            await bot.refresh_state_from_dom()

        # Check if tiles are present; if not, the host needs to deal
        host = mp.host
        host_state = host.current_state
        has_tiles = host_state and any(len(f) > 0 for f in host_state.factories)
        if not has_tiles:
            logger.info(f"[{host.player_name}] No tiles found, emitting dealTiles")
            await host.deal_tiles()
            await asyncio.gather(*(bot.wait_for_state_update(timeout_s=8) for bot in mp.bots))
            await asyncio.sleep(2)
            for bot in mp.bots:
                await bot.refresh_state_from_dom()

        logger.info(f"[{session_id}] Tiles ready, starting game loop")

        # Helper to emit a system log event to frontend + logger
        async def syslog(level: str, player: str, phase: str, msg: str, data: dict = None):
            entry = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "level": level,
                "player": player,
                "phase": phase,
                "msg": msg,
                **({"data": data} if data else {}),
            }
            log_msg = f"[{player}] [{phase}] {msg}"
            if data:
                log_msg += f" {json.dumps(data)}"
            getattr(logger, level, logger.info)(log_msg)
            await _broadcast_state_msg(session_id, {"type": "syslog", "data": entry})

        # 6. Main game loop
        max_total_turns = 500
        total_turns = 0
        last_successful_move_time = time.time()

        while total_turns < max_total_turns:
            # Check game-over for ALL bots FIRST (before any turn logic)
            if total_turns > 0:
                for bot in mp.bots:
                    if not bot.game_over and await bot.check_game_over():
                        await syslog("info", bot.player_name, "game_over",
                                     f"Game over detected after {total_turns} turns")
                if all(bot.game_over for bot in mp.bots):
                    await syslog("info", session_id, "game_over",
                                 f"All bots confirm game over after {total_turns} turns")
                    break
                # If any bot sees game over, check the rest
                if any(bot.game_over for bot in mp.bots):
                    # Give other bots a moment to detect it too
                    await asyncio.sleep(2)
                    for bot in mp.bots:
                        if not bot.game_over:
                            await bot.check_game_over()
                    if all(bot.game_over for bot in mp.bots):
                        break

            any_acted = False

            for bot in mp.bots:
                if bot.game_over:
                    continue

                # Check if it's this bot's turn
                if not await bot.is_my_turn():
                    continue

                turn_start = time.time()

                # Check if we need to deal tiles (new round)
                if await bot.needs_deal():
                    await syslog("info", bot.player_name, "deal", "Dealing tiles for new round")
                    t0 = time.time()
                    await bot.deal_tiles()
                    await bot.wait_for_state_update(timeout_s=8)
                    await asyncio.sleep(1)
                    await bot.refresh_state_from_dom()
                    deal_ms = int((time.time() - t0) * 1000)
                    await syslog("info", bot.player_name, "deal",
                                 f"Tiles dealt in {deal_ms}ms", {"deal_ms": deal_ms})
                    any_acted = True
                    last_successful_move_time = time.time()
                    continue

                # Get fresh state from DOM
                t0 = time.time()
                state = await bot.refresh_state_from_dom()
                dom_ms = int((time.time() - t0) * 1000)
                if not state:
                    await syslog("warning", bot.player_name, "state",
                                 f"DOM parse failed ({dom_ms}ms)")
                    await asyncio.sleep(0.5)
                    continue

                factory_count = sum(len(f) for f in state.factories)
                center_count = len([t for t in state.center_pool if t != "firstPlayer"])
                await syslog("info", bot.player_name, "state",
                             f"State read in {dom_ms}ms: {factory_count} factory tiles, "
                             f"{center_count} center tiles",
                             {"dom_ms": dom_ms, "factory_tiles": factory_count,
                              "center_tiles": center_count, "round": state.round})

                # Verify there are tiles to pick
                if factory_count == 0 and center_count == 0:
                    await syslog("info", bot.player_name, "deal",
                                 "No tiles available, dealing")
                    await bot.deal_tiles()
                    await bot.wait_for_state_update(timeout_s=8)
                    await bot.refresh_state_from_dom()
                    any_acted = True
                    last_successful_move_time = time.time()
                    continue

                # Save state snapshot
                _save_state_snapshot(session_id, step_counter, state, db)

                # Ask ML model for a decision (with timeout)
                player_index = await bot.get_player_index()
                model = bot_models[bot.player_name]

                try:
                    t0 = time.time()
                    action = await asyncio.wait_for(
                        model.decide(state, player_index),
                        timeout=move_timeout_sec,
                    )
                    decision_ms = int((time.time() - t0) * 1000)
                except asyncio.TimeoutError:
                    await syslog("error", bot.player_name, "ml_decide",
                                 f"TIMEOUT after {move_timeout_sec}s")
                    continue
                except Exception as e:
                    await syslog("error", bot.player_name, "ml_decide",
                                 f"Failed: {e}")
                    continue

                from app.azul.rules import get_legal_actions
                n_legal = len(get_legal_actions(state, player_index))
                await syslog("info", bot.player_name, "ml_decide",
                             f"Decided in {decision_ms}ms: {action.color.value} from "
                             f"{action.source_type.value}[{action.source_index}] -> "
                             f"{action.destination.value}[{action.destination_row}] "
                             f"({n_legal} legal options)",
                             {"decision_ms": decision_ms, "legal_actions": n_legal,
                              "action": action.dict()})

                # Execute the move
                t0 = time.time()
                success = await bot.execute_move(action)
                click_ms = int((time.time() - t0) * 1000)

                if not success:
                    await syslog("error", bot.player_name, "execute",
                                 f"Click failed after {click_ms}ms",
                                 {"click_ms": click_ms, "action": action.dict()})
                    continue

                # Wait for state to update (verify the move went through)
                t0 = time.time()
                state_changed = await bot.wait_for_state_update(timeout_s=5)
                ws_wait_ms = int((time.time() - t0) * 1000)

                if not state_changed:
                    new_state = await bot.refresh_state_from_dom()
                    if new_state and _states_equal(state, new_state):
                        await syslog("warning", bot.player_name, "verify",
                                     f"Move had NO effect (state unchanged after {ws_wait_ms}ms). "
                                     f"Rejected by platform?",
                                     {"ws_wait_ms": ws_wait_ms, "click_ms": click_ms,
                                      "action": action.dict()})
                        continue
                    await syslog("info", bot.player_name, "verify",
                                 f"No WS update but DOM changed ({ws_wait_ms}ms) — accepting")
                else:
                    await syslog("info", bot.player_name, "verify",
                                 f"State confirmed via WS in {ws_wait_ms}ms")

                # Move succeeded
                total_ms = int((time.time() - turn_start) * 1000)
                step_counter += 1
                record = MoveRecord(
                    session_id=session_id,
                    step_id=step_counter,
                    player_name=bot.player_name,
                    system_tag=model.name,
                    action=action,
                    game_state_before=state,
                    decision_time_ms=decision_ms,
                    timestamp=datetime.utcnow(),
                )
                # Collect scores and build board snapshot
                cur_scores = {}
                cur_round = 1
                board_snapshot = None
                if state:
                    cur_round = state.round
                    cur_scores = {p.name: p.score for p in state.players}
                    board_snapshot = {
                        "factories": [[t.value if hasattr(t, 'value') else str(t) for t in f] for f in state.factories],
                        "center_pool": state.center_pool,
                        "players": [
                            {
                                "name": p.name,
                                "score": p.score,
                                "pattern_lines": [
                                    [t.value if hasattr(t, 'value') else str(t) for t in row]
                                    for row in p.pattern_lines
                                ],
                                "wall": p.wall,
                                "floor_line": [t.value if hasattr(t, 'value') else str(t) for t in p.floor_line],
                            }
                            for p in state.players
                        ],
                    }

                extra = {
                    "click_ms": click_ms,
                    "ws_wait_ms": ws_wait_ms,
                    "total_ms": total_ms,
                    "legal_actions": n_legal,
                    "round": cur_round,
                    "scores": cur_scores,
                    "board": board_snapshot,
                }
                _save_move_record(session_id, record, db, extra=extra)
                await _broadcast_move(session_id, record, extra=extra)

                if bot.current_state:
                    await _broadcast_state(session_id, bot.current_state)

                await syslog("info", bot.player_name, "move_ok",
                             f"Turn {total_turns} complete in {total_ms}ms "
                             f"(decide={decision_ms}ms click={click_ms}ms ws={ws_wait_ms}ms)",
                             {"step": step_counter, "total_ms": total_ms})

                any_acted = True
                total_turns += 1
                last_successful_move_time = time.time()

            # Check if all bots see game over
            if all(bot.game_over for bot in mp.bots):
                await syslog("info", session_id, "game_over",
                             f"All bots report game over after {total_turns} turns")
                break

            # Check stuck timeout
            stuck_duration = time.time() - last_successful_move_time
            if stuck_duration > move_timeout_sec + stuck_abort_sec:
                abort_reason = (
                    f"No progress for {stuck_duration:.0f}s "
                    f"(limit: {move_timeout_sec}+{stuck_abort_sec}s)"
                )
                await syslog("error", session_id, "abort", abort_reason,
                             {"stuck_sec": round(stuck_duration, 1),
                              "total_turns": total_turns})
                break

            if not any_acted:
                await asyncio.sleep(0.5)

        # 7. Game finished — collect scores and save diagnostics
        scores = {}
        for bot in mp.bots:
            s = await bot.get_scores()
            scores.update(s)

        # Save diagnostic snapshot
        diag = {
            "total_turns": total_turns,
            "step_counter": step_counter,
            "scores": scores,
            "abort_reason": abort_reason,
            "bots": [
                {
                    "name": bot.player_name,
                    "game_over": bot.game_over,
                    "game_started": bot.game_started,
                    "has_state": bot.current_state is not None,
                }
                for bot in mp.bots
            ],
        }
        logger.info(f"[{session_id}] Final: {json.dumps(diag)}")
        _save_state_snapshot(session_id, step_counter + 1,
                            mp.bots[0].current_state or GameStateData(room_name=mp.room_name), db)

        await _broadcast_state_msg(session_id, {
            "type": "game_over",
            "data": {"scores": scores, "total_turns": total_turns, "abort_reason": abort_reason},
        })

        if abort_reason:
            _update_db_status(session_id, SessionStatus.ABORTED, db, scores=scores)
        else:
            _update_db_status(session_id, SessionStatus.COMPLETED, db, scores=scores)

    except asyncio.CancelledError:
        logger.info(f"[{session_id}] Game cancelled")
    except Exception as e:
        logger.error(f"[{session_id}] Game error: {e}", exc_info=True)
        _update_db_status(session_id, SessionStatus.ABORTED, db)
    finally:
        await mp.close_all()
        _active_sessions.pop(session_id, None)
        _session_tasks.pop(session_id, None)


def _states_equal(a: Optional[GameStateData], b: Optional[GameStateData]) -> bool:
    """Check if two game states are functionally the same (same factories/center/scores)."""
    if a is None or b is None:
        return a is b
    try:
        return (
            a.factories == b.factories
            and a.center_pool == b.center_pool
            and [(p.score, p.pattern_lines, p.floor_line) for p in a.players]
            == [(p.score, p.pattern_lines, p.floor_line) for p in b.players]
        )
    except Exception:
        return False


# ---- DB helpers ----

def _update_db_status(session_id: str, status: SessionStatus, db: DBSession,
                      scores: dict = None):
    session = db.query(Session).filter(Session.id == session_id).first()
    if session:
        session.status = status.value
        if status in (SessionStatus.COMPLETED, SessionStatus.ABORTED):
            session.completed_at = datetime.utcnow()
        if scores:
            session.final_scores = json.dumps(scores)
            if scores:
                winner = max(scores, key=scores.get)
                session.winner = winner
        db.commit()


def _save_state_snapshot(session_id: str, step: int, state: GameStateData, db: DBSession):
    gs = GameStateModel(
        session_id=session_id,
        step_id=step,
        state_json=state.json(),
    )
    db.add(gs)
    try:
        db.commit()
    except Exception:
        db.rollback()


def _save_move_record(session_id: str, record: MoveRecord, db: DBSession, extra: dict = None):
    move = Move(
        session_id=session_id,
        step_id=record.step_id,
        player_name=record.player_name,
        system_tag=record.system_tag,
        action_json=record.action.json(),
        decision_time_ms=record.decision_time_ms,
    )
    # Store extra data (board snapshot, scores, timing) in action_json alongside the action
    if extra:
        import json as _json
        action_data = _json.loads(record.action.json())
        action_data["_extra"] = extra
        move.action_json = _json.dumps(action_data)
    db.add(move)
    try:
        db.commit()
    except Exception:
        db.rollback()


# ---- WebSocket broadcast ----

async def _broadcast_state(session_id: str, state: GameStateData):
    await _broadcast_state_msg(session_id, {"type": "state_update", "data": state.dict()})


async def _broadcast_move(session_id: str, record: MoveRecord, extra: dict = None):
    data = {
        "step_id": record.step_id,
        "player_name": record.player_name,
        "system_tag": record.system_tag,
        "action": record.action.dict(),
        "decision_time_ms": record.decision_time_ms,
        "timestamp": record.timestamp.isoformat() + "Z",
    }
    if extra:
        data.update(extra)
    await _broadcast_state_msg(session_id, {"type": "move", "data": data})


async def _broadcast_state_msg(session_id: str, msg: dict):
    conns = _ws_connections.get(session_id, [])
    dead = []
    for ws in conns:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        conns.remove(ws)
