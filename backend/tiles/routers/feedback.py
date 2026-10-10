"""Human evaluation of explanations: collect ratings and summarise them.

Each rating is a participant's judgement of one move's explanation on three 1-5 scales
(understandable, useful, trustworthy) plus an optional comment. ``scripts/analyze_feedback.py``
produces the statistics for the report from the same table.
"""

from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from tiles.models.db import ExplanationFeedback, Move, get_db

router = APIRouter()
ITEMS = ("understandable", "useful", "trustworthy")


class FeedbackIn(BaseModel):
    session_id: str
    step_id: int
    rater: str = Field(min_length=1, max_length=40)
    understandable: int = Field(ge=1, le=5)
    useful: int = Field(ge=1, le=5)
    trustworthy: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


def mean_ci(values: List[int]) -> Dict:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "ci95": None}
    m = statistics.fmean(values)
    if n < 2:
        return {"n": n, "mean": round(m, 3), "ci95": None}
    half = 1.96 * statistics.stdev(values) / math.sqrt(n)
    return {"n": n, "mean": round(m, 3), "ci95": [round(m - half, 3), round(m + half, 3)]}


@router.post("")
def submit_feedback(body: FeedbackIn, db: DBSession = Depends(get_db)):
    move = db.query(Move).filter(Move.session_id == body.session_id, Move.step_id == body.step_id).first()
    if not move:
        raise HTTPException(status_code=404, detail="No such move")
    row = ExplanationFeedback(
        session_id=body.session_id, step_id=body.step_id, rater=body.rater.strip(),
        model=move.system_tag, understandable=body.understandable, useful=body.useful,
        trustworthy=body.trustworthy, comment=body.comment,
    )
    db.add(row)
    db.commit()
    return {"id": row.id}


@router.get("/summary")
def feedback_summary(db: DBSession = Depends(get_db)):
    rows = db.query(ExplanationFeedback).all()
    by_model: Dict[str, List[ExplanationFeedback]] = {}
    for r in rows:
        by_model.setdefault(r.model or "unknown", []).append(r)
    return {
        "ratings": len(rows),
        "raters": len({r.rater for r in rows}),
        "overall": {i: mean_ci([getattr(r, i) for r in rows]) for i in ITEMS},
        "by_model": {m: {i: mean_ci([getattr(r, i) for r in rs]) for i in ITEMS} for m, rs in by_model.items()},
    }


@router.get("/{session_id}")
def feedback_for_session(session_id: str, db: DBSession = Depends(get_db)):
    rows = db.query(ExplanationFeedback).filter(ExplanationFeedback.session_id == session_id).all()
    return [{"step_id": r.step_id, "rater": r.rater, "understandable": r.understandable, "useful": r.useful,
             "trustworthy": r.trustworthy, "comment": r.comment} for r in rows]
