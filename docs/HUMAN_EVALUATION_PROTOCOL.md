# Human-centred evaluation of explanations: protocol

**Status:** the instrument (rating widget, API, database table, analysis script, control condition) is built and tested. **No participant data has been collected yet**; collecting it needs real participants, so it has to be run by the team. Do not report results until it has been.

## Question

Do natural-language rationales make the agent's moves easier to understand, more useful and more trustworthy than a numbers-only explanation (the top-3 move scores)?

## Design

Between-subjects, two conditions, same recorded games:

| Condition | What the participant sees under each move | URL |
|---|---|---|
| **A: rationale** | one to four sentences, built from engine facts, plus the opponent read | `http://localhost:8080` (default) |
| **B: scores only** (control) | the model's top-3 moves with their heuristic scores | `http://localhost:8080/?explain=scores` |

Assign participants to A or B alternately (A, B, A, B, ...) as they arrive. Use the same recorded game for everyone.

## Participants

At least 10 (5 per condition); more is better. Ideally mix people who have played Azul with people who have not. Record experience level on the rater ID, e.g. `P03-novice`, `P04-expert`. Participants should not be team members.

## Materials

1. A completed game recorded with the Minimax player: run one session (`MinimaxPlayer` vs `GreedyPlayer`), or use `docs/evidence/live_game_2p_minimax_with_rationales.json`'s session in your own database.
2. The Replay tab (play, pause, step, jump).
3. The rating widget under each explained move.

## Procedure (about 15 minutes per participant)

1. Give a 2-minute description of Azul (drafting tiles, pattern lines, floor penalties, wall scoring).
2. Open the Replay of the recorded game in the participant's condition.
3. Ask them to step to **10 pre-chosen moves** (pick moves with a mix of line completions, floor dumps, first-player-token takes and denials; write the move numbers down once and reuse them).
4. At each move the participant rates, from 1 (poor) to 5 (excellent): **Easy to understand**, **Useful**, **Trustworthy**, and optionally leaves a comment. They enter their rater ID once; it is remembered.
5. Optional comprehension check after each move: "Why do you think the agent did that?" (free text, note whether the answer matches the facts).

## Analysis

```bash
python scripts/analyze_feedback.py                # mean and 95% CI per scale, per player model, with comments
curl http://localhost:8080/api/feedback/summary   # the same, as JSON
```

The analysis script groups by the model that made the move. To compare conditions, give raters in condition B an ID suffix (e.g. `P02-B`) and filter the raw rows from `GET /api/feedback/{session_id}`, then compare the two groups with a Mann-Whitney U test (ordinal ratings, small samples). Report n, medians, and the test result honestly, including a null result.

## Automated check that already exists

Separately from the human study, `backend/tests/test_explainer.py` verifies the *faithfulness* of every claim in a rationale (tiles taken, line completion, overflow, floor cost, token, wall points awarded at round end, denial) by simulating the move in the game engine, over more than 1,500 positions. A rationale therefore cannot claim something the position does not support; the human study measures whether people find the text clear, useful and trustworthy.
