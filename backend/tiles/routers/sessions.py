"""Session management API routes — multi-bot orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession

from tiles.azul.rules import get_legal_actions, is_game_over
from tiles.engine.play_engine import MultiPlayerSession
from tiles import tracking
from tiles.explain.explainer import Explainer
from tiles.ml.archetypes import move_record
from tiles.ml.registry import registry
from tiles.auth import api_key_ok
from tiles.validation import ROOM_RE, check_platform_url, check_session_players
from tiles.engine.human_tracker import HumanMoveTracker
from tiles.models.db import Move, Session, get_db, GameState as GameStateModel
from tiles.models.schemas import (
    DestinationType,
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
MAX_CONCURRENT_SESSIONS = int(os.environ.get("TILES_MAX_SESSIONS", "3"))
HUMAN_IDLE_TIMEOUT_S = float(os.environ.get("TILES_HUMAN_IDLE_TIMEOUT_S", "1800"))   # abort if nobody moves for this long
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
    problems = check_session_players(
        req.players, [p["name"] for p in registry.list_players()],
        default_name=lambda p: f"Bot_{p.type}_{p.slot}")
    if not ROOM_RE.match(req.room_name):
        problems.append("room_name may only contain letters, digits, space, '_', '.' and '-'")
    url_problem = check_platform_url(req.platform_url)
    if url_problem:
        problems.append(url_problem)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
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

    if session_id in _session_tasks or session_id in _active_sessions:
        raise HTTPException(status_code=400, detail="Session is already running")
    if session.status not in (SessionStatus.CREATED.value, SessionStatus.LOBBY.value):
        raise HTTPException(status_code=400, detail=f"Session is already {session.status}")
    if len(_active_sessions) >= MAX_CONCURRENT_SESSIONS:
        raise HTTPException(status_code=429, detail=f"At most {MAX_CONCURRENT_SESSIONS} sessions can run at once "
                                                    "(each runs one Chromium per bot); stop or wait for one to finish")

    player_config = json.loads(session.player_config)
    bot_slots = [p for p in player_config if p.get("type") != "human"]
    human_slots = [p for p in player_config if p.get("type") == "human"]

    if not bot_slots:
        raise HTTPException(status_code=400, detail="At least one machine player is required")

    # Validate all bot model types exist
    bot_models = {}
    for slot in bot_slots:
        model_name = slot["type"]
        model = registry.create_player(model_name)  # fresh instance per bot (per-game state)
        if not model:
            available = [p["name"] for p in registry.list_players()]
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model_name}' not found. Available: {available}",
            )
        model.set_time_limit(session.move_timeout_sec)
        player_name = slot.get("name") or f"Bot_{model_name}_{slot['slot']}"
        if player_name in bot_models:
            raise HTTPException(status_code=400, detail=f"Duplicate player name '{player_name}'")
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

    if session.status in (SessionStatus.COMPLETED.value, SessionStatus.ABORTED.value):
        return {"status": session.status, "session_id": session_id}

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
    if not api_key_ok(websocket.query_params.get("api_key")):
        await websocket.close(code=1008)          # policy violation: missing / invalid API key
        return
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
                        "data": bot.current_state.model_dump(mode="json"),
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

        human_tracker = HumanMoveTracker([b.player_name for b in mp.bots]) if mp.human_count else None

        async def record_human_moves():
            nonlocal step_counter, last_successful_move_time
            if human_tracker is None:
                return
            ref = next((b.ws_state or b.current_state for b in mp.bots if (b.ws_state or b.current_state)), None)
            for om in human_tracker.update(ref):
                step_counter += 1
                record = MoveRecord(session_id=session_id, step_id=step_counter, player_name=om.player_name,
                                    system_tag="human", action=om.action, game_state_before=om.before,
                                    decision_time_ms=None, timestamp=datetime.utcnow())
                try:
                    rec = move_record(om.before, om.player_index, om.action)
                    for other_bot in mp.bots:
                        bot_models[other_bot.player_name].observe(rec, other_bot.player_name)
                except Exception:
                    logger.exception("observe hook failed")
                extra = {"inferred": True, "round": om.before.round,
                         "scores": {p.name: p.score for p in om.before.players},
                         "board": _board_snapshot(om.before),
                         "commentary": _commentary(om.before, om.player_index, om.action)}
                _save_state_snapshot(session_id, step_counter, om.before, db)
                _save_move_record(session_id, record, db, extra=extra)
                await _broadcast_move(session_id, record, extra=extra)
                await syslog("info", om.player_name, "human_move",
                             f"Recorded human move: {om.action.color.value} from "
                             f"{om.action.source_type.value}[{om.action.source_index}] -> "
                             f"{om.action.destination.value}[{om.action.destination_row}]")
                last_successful_move_time = time.time()

        while total_turns < max_total_turns:
            # Record moves made by humans (inferred from the board) before any bot acts on the new state
            await record_human_moves()

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
                    await bot.refresh_state_from_dom()
                    any_acted = True
                    last_successful_move_time = time.time()
                    continue

                # Save state snapshot
                _save_state_snapshot(session_id, step_counter + 1, state, db)

                # Ask ML model for a decision (with timeout)
                player_index = await bot.get_player_index()
                model = bot_models[bot.player_name]

                try:
                    t0 = time.time()
                    action = await asyncio.wait_for(
                        _decide(model, state, player_index),
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

                # Validator gate: never execute a move the rules engine doesn't allow.
                legal = get_legal_actions(state, player_index)
                n_legal = len(legal)
                if action not in legal:
                    await syslog("error", bot.player_name, "validate",
                                 f"Rejected illegal action from {model.name}",
                                 {"action": action.model_dump(), "legal_actions": n_legal})
                    continue
                await syslog("info", bot.player_name, "ml_decide",
                             f"Decided in {decision_ms}ms: {action.color.value} from "
                             f"{action.source_type.value}[{action.source_index}] -> "
                             f"{action.destination.value}[{action.destination_row}] "
                             f"({n_legal} legal options)",
                             {"decision_ms": decision_ms, "legal_actions": n_legal,
                              "action": action.model_dump()})

                # Execute the move
                t0 = time.time()
                bot.arm_state_event()
                success = await bot.execute_move(action)
                click_ms = int((time.time() - t0) * 1000)
                intended_action = action

                if not success:
                    await syslog("error", bot.player_name, "execute",
                                 f"Click failed after {click_ms}ms",
                                 {"click_ms": click_ms, "action": action.model_dump()})
                    continue

                # Wait for state to update (verify the move went through)
                t0 = time.time()
                state_changed = await bot.wait_for_state_update(timeout_s=5, clear=False)
                ws_wait_ms = int((time.time() - t0) * 1000)

                if not state_changed:
                    new_state = await bot.refresh_state_from_dom()
                    if new_state and _states_equal(state, new_state):
                        await syslog("warning", bot.player_name, "verify",
                                     f"Move had NO effect (state unchanged after {ws_wait_ms}ms). "
                                     f"Rejected by platform?",
                                     {"ws_wait_ms": ws_wait_ms, "click_ms": click_ms,
                                      "action": action.model_dump()})
                        continue
                    await syslog("info", bot.player_name, "verify",
                                 f"No WS update but DOM changed ({ws_wait_ms}ms) — accepting")
                else:
                    await syslog("info", bot.player_name, "verify",
                                 f"State confirmed via WS in {ws_wait_ms}ms")

                # Record what was actually played if the platform forced a floor fallback
                fell_back = bool(getattr(success, "fell_back_to_floor", False))
                if fell_back:
                    action = GameAction(
                        source_type=action.source_type,
                        source_index=action.source_index,
                        color=action.color,
                        destination=DestinationType.FLOOR,
                        destination_row=None,
                    )
                    await syslog("warning", bot.player_name, "execute",
                                 "Platform rejected pattern line; played floor instead",
                                 {"intended": intended_action.model_dump(), "played": action.model_dump()})

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
                # Let every model observe the move (adaptive players model opponents from it)
                try:
                    rec = move_record(state, player_index, action)
                    for other_bot in mp.bots:
                        other_model = bot_models[other_bot.player_name]
                        other_model.observe(rec, other_bot.player_name)
                except Exception:
                    logger.exception("observe hook failed")

                # Collect scores and build board snapshot
                cur_scores = {}
                cur_round = 1
                board_snapshot = None
                if state:
                    cur_round = state.round
                    cur_scores = {p.name: p.score for p in state.players}
                    board_snapshot = _board_snapshot(state)

                extra = {
                    "click_ms": click_ms,
                    "ws_wait_ms": ws_wait_ms,
                    "total_ms": total_ms,
                    "fell_back_to_floor": fell_back,
                    "explanation": _explain(state, player_index, action, getattr(model, "last_explanation", None)),
                    "commentary": _commentary(state, player_index, action),
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
            # Humans may think longer than the bot timeout, so only abort on
            # stalls in bot-only games.
            stuck_duration = time.time() - last_successful_move_time
            stuck_limit = (move_timeout_sec + stuck_abort_sec) if mp.human_count == 0 else HUMAN_IDLE_TIMEOUT_S
            if stuck_duration > stuck_limit:
                abort_reason = f"No progress for {stuck_duration:.0f}s (limit: {stuck_limit:.0f}s)"
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

        # A game only counts as completed if the board shows a finished wall row.
        if not abort_reason:
            final_state = await mp.bots[0].refresh_state_from_dom()
            if final_state is None or not is_game_over(final_state):
                abort_reason = "Stopped without any player completing a wall row (game did not finish)"
                await syslog("error", session_id, "abort", abort_reason)

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
            _update_db_status(session_id, SessionStatus.COMPLETED, db, scores=scores,
                              completed_rows=_completed_rows(mp.bots[0].current_state))
        # experiment tracking (MLflow); runs in a thread and can never fail the game
        asyncio.create_task(asyncio.to_thread(tracking.log_session_run, session_id))

    except asyncio.CancelledError:
        logger.info(f"[{session_id}] Game cancelled")
    except Exception as e:
        logger.error(f"[{session_id}] Game error: {e}", exc_info=True)
        _update_db_status(session_id, SessionStatus.ABORTED, db)
    finally:
        await mp.close_all()
        _active_sessions.pop(session_id, None)
        _session_tasks.pop(session_id, None)


async def _decide(model, state: GameStateData, player_index: int) -> GameAction:
    """Ask a model for its move. CPU-bound search players run in a worker thread (on a copy of the
    state) so that thinking never blocks the event loop; the move timeout can then actually fire."""
    if not getattr(model, "cpu_bound", False):
        return await model.decide(state, player_index)
    snapshot = state.model_copy(deep=True)
    return await asyncio.to_thread(lambda: asyncio.run(model.decide(snapshot, player_index)))


_explainer = Explainer()


def _explain(state, player_index, action, model_explanation):
    """Model explanation (alternatives, adaptation) plus a natural-language rationale and its facts."""
    try:
        out = _explainer.explain(state, player_index, action, model_explanation)
    except Exception:
        logger.exception("explainer failed")
        return model_explanation or None
    merged = dict(model_explanation or {})
    merged["rationale"], merged["facts"] = out["rationale"], out["facts"]
    return merged


def _commentary(state, player_index, action):
    try:
        return _explainer.commentary(state, player_index, action)
    except Exception:
        return None


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


def _board_snapshot(state: GameStateData) -> dict:
    """JSON board stored with each move (replay, profiling features)."""
    val = lambda t: t.value if hasattr(t, "value") else str(t)  # noqa: E731
    return {
        "factories": [[val(t) for t in f] for f in state.factories],
        "center_pool": state.center_pool,
        "players": [
            {"name": p.name, "score": p.score,
             "pattern_lines": [[val(t) for t in row] for row in p.pattern_lines],
             "wall": p.wall, "floor_line": [val(t) for t in p.floor_line]}
            for p in state.players
        ],
    }


# ---- DB helpers ----

def pick_winner(scores: dict, completed_rows: Optional[dict] = None) -> Optional[str]:
    """Azul winner: highest score; ties go to the player with more completed wall rows; a tie that
    remains is a shared win, reported as ``"A / B"``."""
    if not scores:
        return None
    rows = completed_rows or {}
    key = lambda n: (scores[n], rows.get(n, 0))  # noqa: E731
    best = max(key(n) for n in scores)
    return " / ".join(n for n in scores if key(n) == best)


def _completed_rows(state: Optional[GameStateData]) -> dict:
    if state is None:
        return {}
    return {p.name: sum(1 for row in p.wall if all(row)) for p in state.players}


def _update_db_status(session_id: str, status: SessionStatus, db: DBSession,
                      scores: dict = None, completed_rows: dict = None):
    session = db.query(Session).filter(Session.id == session_id).first()
    if session:
        session.status = status.value
        if status in (SessionStatus.COMPLETED, SessionStatus.ABORTED):
            session.completed_at = datetime.utcnow()
        if scores:
            session.final_scores = json.dumps(scores)
            session.winner = pick_winner(scores, completed_rows)
        db.commit()


def _save_state_snapshot(session_id: str, step: int, state: GameStateData, db: DBSession):
    """Store the state that precedes move `step`; re-saving the same step (a retried
    move) replaces the earlier snapshot rather than failing on the unique constraint."""
    existing = (
        db.query(GameStateModel)
        .filter(GameStateModel.session_id == session_id, GameStateModel.step_id == step)
        .first()
    )
    if existing:
        existing.state_json = state.model_dump_json()
    else:
        db.add(GameStateModel(session_id=session_id, step_id=step, state_json=state.model_dump_json()))
    try:
        db.commit()
    except Exception:
        logger.exception("Failed to save state snapshot for step %s", step)
        db.rollback()


def _save_move_record(session_id: str, record: MoveRecord, db: DBSession, extra: dict = None):
    move = Move(
        session_id=session_id,
        step_id=record.step_id,
        player_name=record.player_name,
        system_tag=record.system_tag,
        action_json=record.action.model_dump_json(),
        decision_time_ms=record.decision_time_ms,
    )
    # Store extra data (board snapshot, scores, timing) in action_json alongside the action
    if extra:
        import json as _json
        action_data = _json.loads(record.action.model_dump_json())
        action_data["_extra"] = extra
        move.action_json = _json.dumps(action_data)
    db.add(move)
    try:
        db.commit()
    except Exception:
        db.rollback()


# ---- WebSocket broadcast ----

async def _broadcast_state(session_id: str, state: GameStateData):
    await _broadcast_state_msg(session_id, {"type": "state_update", "data": state.model_dump(mode="json")})


async def _broadcast_move(session_id: str, record: MoveRecord, extra: dict = None):
    data = {
        "step_id": record.step_id,
        "player_name": record.player_name,
        "system_tag": record.system_tag,
        "action": record.action.model_dump(),
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
            logger.warning("Dropping WebSocket client for %s after send failure", session_id, exc_info=True)
            dead.append(ws)
    for ws in dead:
        conns.remove(ws)
