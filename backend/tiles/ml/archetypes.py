"""Opponent archetype discovery: behavioural features + k-means clustering.

Input is the move format used by the ledger / history API::

    {"player_name": str,
     "action": {source_type, source_index, color, destination, destination_row},
     "board": {"factories": [[color]], "center_pool": [str],
               "players": [{"name", "pattern_lines", "wall", "floor_line"}]}}

where ``board`` is the state *before* the move. The same extractor is used for
live games (from the DB) and for simulated self-play (scripts/train_archetypes.py),
so a model trained on simulation can classify ledger games.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

COLORS = ["blue", "yellow", "red", "black", "white"]

FEATURE_NAMES = [
    "color_concentration",   # 0 = picks all colours evenly, 1 = one colour only
    "center_share",          # fraction of picks taken from the center
    "floor_share",           # fraction of moves sent straight to the floor
    "mean_row",              # mean pattern-line row chosen (0 small .. 1 large)
    "overflow_rate",         # tiles overflowing to floor / tiles picked
    "block_rate",            # picks of a colour an opponent was building
    "token_rate",            # center picks that also took the first-player token
    "mean_pick_size",        # tiles taken per move (normalised by 4)
    "small_row_share",       # share of line placements on rows 1-2
    "repeat_color_rate",     # picks of a colour already on the player's own board
]

FEATURE_DESCRIPTIONS = {
    "color_concentration": "sticks to few colours",
    "center_share": "drafts from the center pool",
    "floor_share": "dumps tiles straight to the floor",
    "mean_row": "builds large pattern lines",
    "overflow_rate": "overfills lines and spills to the floor",
    "block_rate": "takes colours opponents are building",
    "token_rate": "takes the first-player token",
    "mean_pick_size": "takes large tile groups",
    "small_row_share": "favours the two smallest pattern lines",
    "repeat_color_rate": "keeps picking colours it already holds",
}

MIN_MOVES = 5

# Wall layout (row r, column c -> colour); matches tiles.azul.rules.WALL_PATTERN
WALL_COLORS = [[COLORS[(c - r) % 5] for c in range(5)] for r in range(5)]


def move_record(state, player_index: int, action) -> dict:
    """Ledger-format move dict (action + pre-move board) from a GameStateData and GameAction."""
    val = lambda t: getattr(t, "value", t)  # noqa: E731
    return {
        "player_index": player_index,
        "player_name": state.players[player_index].name,
        "action": {
            "source_type": val(action.source_type), "source_index": action.source_index,
            "color": val(action.color), "destination": val(action.destination),
            "destination_row": action.destination_row,
        },
        "board": {
            "factories": [[val(t) for t in f] for f in state.factories],
            "center_pool": [val(t) for t in state.center_pool],
            "players": [{"name": p.name,
                         "pattern_lines": [[val(t) for t in r] for r in p.pattern_lines],
                         "wall": [list(r) for r in p.wall],
                         "floor_line": [val(t) for t in p.floor_line]} for p in state.players],
        },
    }


def state_from_record(record: dict):
    """Rebuild a GameStateData from a ledger-format move record's pre-move board (or None)."""
    from tiles.models.schemas import GameStateData, PlayerState, TileColor

    board = record.get("board")
    if not board:
        return None
    try:
        players = [
            PlayerState(
                index=i, name=p["name"], score=p.get("score", 0),
                pattern_lines=[[TileColor(c) for c in row] for row in p["pattern_lines"]],
                wall=[list(map(bool, r)) for r in p.get("wall") or [[False] * 5 for _ in range(5)]],
                floor_line=[TileColor(c) for c in p.get("floor_line", [])],
            )
            for i, p in enumerate(board["players"])
        ]
        return GameStateData(
            factories=[[TileColor(c) for c in f] for f in board["factories"]],
            center_pool=list(board["center_pool"]), players=players,
        )
    except (KeyError, ValueError):
        return None


def _picked_count(board: dict, action: dict) -> int:
    color = action["color"]
    if action["source_type"] == "factory":
        idx = action.get("source_index")
        facs = board.get("factories", [])
        if idx is not None and idx < len(facs):
            return sum(1 for t in facs[idx] if t == color)
        return 0
    return sum(1 for t in board.get("center_pool", []) if t == color)


def extract_features(moves: Sequence[dict], player_name: str) -> Optional[np.ndarray]:
    """Behavioural feature vector for one player over one game, or None if too few moves."""
    mine = [m for m in moves if m.get("player_name") == player_name and m.get("board")]
    if len(mine) < MIN_MOVES:
        return None

    n = len(mine)
    colors = Counter(m["action"]["color"] for m in mine)
    shares = np.array([colors.get(c, 0) / n for c in COLORS])
    # Herfindahl index rescaled to [0, 1]
    conc = (float((shares ** 2).sum()) - 1 / len(COLORS)) / (1 - 1 / len(COLORS))

    center = floor = 0
    rows: List[int] = []
    picked_total = overflow_total = blocks = token = center_picks = repeats = 0

    for m in mine:
        a, board = m["action"], m["board"]
        k = _picked_count(board, a)
        picked_total += k
        if a["source_type"] == "center":
            center += 1
            center_picks += 1
            if "firstPlayer" in board.get("center_pool", []):
                token += 1
        me = next((p for p in board.get("players", []) if p["name"] == player_name), None)
        if me is not None:
            held = any(a["color"] in line for line in me["pattern_lines"]) or any(
                me["wall"][r][c] and WALL_COLORS[r][c] == a["color"]
                for r in range(5) for c in range(5)) if me.get("wall") else any(
                a["color"] in line for line in me["pattern_lines"])
            repeats += held
        if a["destination"] == "floor":
            floor += 1
            overflow_total += k
        else:
            row = a["destination_row"]
            rows.append(row)
            if me is not None:
                space = (row + 1) - len(me["pattern_lines"][row])
                overflow_total += max(0, k - space)
        for opp in board.get("players", []):
            if opp["name"] == player_name:
                continue
            if any(len(line) and line[0] == a["color"] and len(line) < i + 1
                   for i, line in enumerate(opp["pattern_lines"])):
                blocks += 1
                break

    feats = [
        conc,
        center / n,
        floor / n,
        (float(np.mean(rows)) / 4.0) if rows else 0.0,
        overflow_total / picked_total if picked_total else 0.0,
        blocks / n,
        (token / center_picks) if center_picks else 0.0,
        min(1.0, (picked_total / n) / 4.0),
        (sum(1 for r in rows if r <= 1) / len(rows)) if rows else 0.0,
        repeats / n,
    ]
    return np.array(feats, dtype=float)


@dataclass
class Prediction:
    archetype: str
    confidence: float          # classifier: probability of the label; k-means: centroid margin
    scores: Dict[str, float]   # classifier: class probabilities; k-means: centroid distances
    standout_features: List[dict]   # features that deviate most from the population mean


class ArchetypeModel:
    """Standardise -> k-means. Cluster ids are mapped to readable labels."""

    def __init__(self, mean, std, centroids, labels: List[str]):
        self.mean = np.asarray(mean, dtype=float)
        self.std = np.where(np.asarray(std, dtype=float) < 1e-9, 1.0, np.asarray(std, dtype=float))
        self.centroids = np.asarray(centroids, dtype=float)
        self.labels = list(labels)

    # --- training ---
    @classmethod
    def fit(cls, X: np.ndarray, k: int, seed: int = 0, labels: Optional[Sequence[str]] = None,
            y: Optional[Sequence[str]] = None) -> "ArchetypeModel":
        """Fit k-means. If ground-truth labels ``y`` are given, each cluster is named by its
        majority label (used for simulated data where the generating archetype is known)."""
        from sklearn.cluster import KMeans

        mean, std = X.mean(axis=0), X.std(axis=0)
        Z = (X - mean) / np.where(std < 1e-9, 1.0, std)
        km = KMeans(n_clusters=k, n_init=20, random_state=seed).fit(Z)
        if y is not None:
            names = []
            for c in range(k):
                members = [y[i] for i in range(len(y)) if km.labels_[i] == c]
                names.append(Counter(members).most_common(1)[0][0] if members else f"cluster_{c}")
            # disambiguate duplicate names
            seen: Counter = Counter()
            out = []
            for nme in names:
                seen[nme] += 1
                out.append(nme if seen[nme] == 1 else f"{nme}~{seen[nme]}")
            names = out
        else:
            names = list(labels) if labels else [f"cluster_{c}" for c in range(k)]
        return cls(mean, std, km.cluster_centers_, names)

    # --- inference ---
    def _z(self, x: np.ndarray) -> np.ndarray:
        return (np.asarray(x, dtype=float) - self.mean) / self.std

    def predict_label(self, x: np.ndarray) -> str:
        return self.labels[int(np.argmin(np.linalg.norm(self.centroids - self._z(x), axis=1)))]

    def predict(self, x: np.ndarray) -> Prediction:
        z = self._z(x)
        d = np.linalg.norm(self.centroids - z, axis=1)
        order = np.argsort(d)
        best = int(order[0])
        second = float(d[order[1]]) if len(d) > 1 else float(d[best]) + 1.0
        conf = 0.0 if second == 0 else max(0.0, min(1.0, (second - d[best]) / second))
        top = np.argsort(-np.abs(z))[:3]
        standouts = [
            {"feature": FEATURE_NAMES[i], "value": round(float(x[i]), 3), "z": round(float(z[i]), 2),
             "meaning": ("high: " if z[i] > 0 else "low: ") + FEATURE_DESCRIPTIONS[FEATURE_NAMES[i]]}
            for i in top
        ]
        return Prediction(self.labels[best], round(conf, 3),
                          {self.labels[i]: round(float(d[i]), 3) for i in range(len(d))}, standouts)


class ArchetypeClassifier:
    """Standardise -> multinomial logistic regression, stored as plain arrays (no pickle).

    Chosen over k-means for identification: the per-feature contributions
    (coefficient x z-score) give a faithful, human-readable reason for each label.
    """

    def __init__(self, mean, std, coef, intercept, classes: List[str]):
        self.mean = np.asarray(mean, dtype=float)
        std = np.asarray(std, dtype=float)
        self.std = np.where(std < 1e-9, 1.0, std)
        self.coef = np.asarray(coef, dtype=float)          # (n_classes, n_features)
        self.intercept = np.asarray(intercept, dtype=float)
        self.classes = list(classes)

    @classmethod
    def fit(cls, X: np.ndarray, y: Sequence[str], C: float = 1.0) -> "ArchetypeClassifier":
        from sklearn.linear_model import LogisticRegression

        mean, std = X.mean(axis=0), X.std(axis=0)
        Z = (X - mean) / np.where(std < 1e-9, 1.0, std)
        lr = LogisticRegression(C=C, max_iter=5000).fit(Z, list(y))
        return cls(mean, std, lr.coef_, lr.intercept_, list(lr.classes_))

    def _probs(self, z: np.ndarray) -> np.ndarray:
        logits = self.coef @ z + self.intercept
        e = np.exp(logits - logits.max())
        return e / e.sum()

    def predict_label(self, x: np.ndarray) -> str:
        return self.classes[int(np.argmax(self._probs((np.asarray(x, dtype=float) - self.mean) / self.std)))]

    def predict(self, x: np.ndarray) -> Prediction:
        x = np.asarray(x, dtype=float)
        z = (x - self.mean) / self.std
        p = self._probs(z)
        best = int(np.argmax(p))
        contrib = self.coef[best] * z
        top = np.argsort(-contrib)[:3]
        standouts = [
            {"feature": FEATURE_NAMES[i], "value": round(float(x[i]), 3), "z": round(float(z[i]), 2),
             "contribution": round(float(contrib[i]), 2),
             "meaning": ("high: " if z[i] > 0 else "low: ") + FEATURE_DESCRIPTIONS[FEATURE_NAMES[i]]}
            for i in top if contrib[i] > 0
        ]
        return Prediction(self.classes[best], round(float(p[best]), 3),
                          {self.classes[i]: round(float(p[i]), 3) for i in range(len(p))}, standouts)

    def save(self, path: Path, meta: Optional[dict] = None) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({
            "type": "logistic_regression", "feature_names": FEATURE_NAMES,
            "mean": self.mean.tolist(), "std": self.std.tolist(),
            "coef": self.coef.tolist(), "intercept": self.intercept.tolist(),
            "classes": self.classes, "meta": meta or {},
        }, indent=2))

    @classmethod
    def load(cls, path: Path) -> "ArchetypeClassifier":
        d = json.loads(Path(path).read_text())
        if d["feature_names"] != FEATURE_NAMES:
            raise ValueError("Archetype model was trained with different features; retrain it")
        return cls(d["mean"], d["std"], d["coef"], d["intercept"], d["classes"])


DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "archetype_classifier.json"
