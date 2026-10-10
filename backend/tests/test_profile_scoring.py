"""Profile numbers: scores come from the latest/final recorded scores, and floor use counts overflow tiles."""

import json

from fastapi.testclient import TestClient

from tiles.main import app
from tiles.ml.analyzers import BasicProfileAnalyzer, _tiles_to_floor
from tiles.models.db import Move, Session, get_db


def board(factory, pattern_lines, center=()):
    return {"factories": [factory], "center_pool": list(center),
            "players": [{"name": "D", "score": 0, "pattern_lines": pattern_lines, "wall": [[False] * 5] * 5, "floor_line": []}]}


def mv(player, step, color="red", src="factory", dest="pattern_line", row=0, scores=None, brd=None):
    m = {"step_id": step, "player_name": player,
         "action": {"source_type": src, "source_index": 0 if src == "factory" else None, "color": color,
                    "destination": dest, "destination_row": row}}
    if scores is not None:
        m["scores"] = scores
    if brd is not None:
        m["board"] = brd
    return m


EMPTY = [[], [], [], [], []]


def test_overflow_tiles_count_as_floor_tiles():
    # 4 red onto row 1 (capacity 2, empty): 2 fit, 2 overflow
    assert _tiles_to_floor(mv("D", 1, row=1, brd=board(["red"] * 4, EMPTY)), "D") == (4, 2)
    # row already holding 1 tile: only 1 space, 3 overflow
    assert _tiles_to_floor(mv("D", 1, row=1, brd=board(["red"] * 4, [[], ["red"], [], [], []])), "D") == (4, 3)
    # straight to the floor: everything taken is on the floor
    assert _tiles_to_floor(mv("D", 1, dest="floor", row=None, brd=board(["red"] * 3 + ["blue"], EMPTY)), "D") == (3, 3)
    # from the centre pool, a perfect fit, the first-player token is not a tile
    assert _tiles_to_floor(mv("D", 1, src="center", row=2, brd=board([], EMPTY, ["firstPlayer", "red", "red"])), "D") == (2, 0)
    # no snapshot or an unreadable one: unknown
    assert _tiles_to_floor(mv("D", 1), "D") is None
    assert _tiles_to_floor(mv("Z", 1, brd=board(["red"], EMPTY)), "Z") is None


def test_floor_share_uses_tiles_and_changes_the_style_label():
    # never sends a move straight to the floor, but overflows heavily: 'conservative' by moves, risky by tiles
    moves = [mv("D", i, row=0, brd=board(["red"] * 4, EMPTY)) for i in range(1, 6)]     # each: 4 taken, 3 overflow
    p = BasicProfileAnalyzer().analyze("D", moves)
    assert p["destination_split"]["floor"] == 0
    assert p["floor_tiles"] == {"taken": 20, "on_floor": 15, "pct": 75}
    assert "aggressive" in p["style"] and "conservative" not in p["style"]
    assert "0% of moves went straight to the floor; 75% of the tiles taken (15 of 20)" in p["summary"]


def test_without_snapshots_the_move_based_floor_figure_is_used():
    p = BasicProfileAnalyzer().analyze("D", [mv("D", i, dest="floor", row=None) for i in range(1, 4)])
    assert p["floor_tiles"] is None and "aggressive" in p["style"]
    assert "Floor usage: 100% of moves went straight to the floor." in p["summary"]


def test_score_prefers_final_then_latest_anywhere_in_the_game():
    moves = [mv("D", 1, scores={"D": 5, "O": 0}), mv("O", 2, scores={"D": 5, "O": 3}), mv("D", 3, scores={"D": 9, "O": 3}),
             mv("O", 4, scores={"D": 12, "O": 3})]                         # a later snapshot of D's score, from O's move
    a = BasicProfileAnalyzer()
    live = a.analyze("D", moves)
    assert live["final_score"] == 12 and live["score_is_final"] is False
    assert "had 12 points at the latest recorded position" in live["summary"]
    done = a.analyze("D", moves, {"D": 41, "O": 30})
    assert done["final_score"] == 41 and done["score_is_final"] is True
    assert done["score_trajectory"] == [5, 9, 41]                           # the end result is appended
    assert "finished with 41 points" in done["summary"]
    assert a.analyze("D", [mv("D", 1)])["final_score"] == 0                 # no score data at all


def test_routes_use_recorded_final_scores_only_for_completed_sessions(db):
    for sid, status in (("done", "completed"), ("live", "playing")):
        db.add(Session(id=sid, room_name=sid, platform_url="https://buddyboardgames.com/azul", browser_mode="headless",
                       status=status, player_config="[]", move_timeout_sec=5, stuck_abort_sec=2,
                       final_scores=json.dumps({"D": 41, "O": 30})))
        for i, (who, sc) in enumerate((("D", 5), ("O", 3), ("D", 9)), start=1):
            action = {"source_type": "factory", "source_index": 0, "color": "red", "destination": "pattern_line",
                      "destination_row": 0, "_extra": {"scores": {"D": sc if who == "D" else 5, "O": 3}}}
            db.add(Move(session_id=sid, step_id=i, player_name=who, action_json=json.dumps(action), decision_time_ms=1))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as c:
            full = c.post("/api/profiler/done/analyze?player_name=D").json()
            assert full["final_score"] == 41 and full["score_is_final"] is True
            mid = c.post("/api/profiler/live/analyze?player_name=D").json()
            assert mid["score_is_final"] is False and mid["final_score"] != 41
            ins = c.get("/api/profiler/done/insights").json()["insights"]
            assert any("finished with 41 points" in i["summary"] for i in ins)
            early = c.get("/api/profiler/done/insights?upto_step=2").json()["insights"]
            assert all("finished with" not in i["summary"] for i in early)    # a profile "as of move 2" is not final
    finally:
        app.dependency_overrides.clear()
