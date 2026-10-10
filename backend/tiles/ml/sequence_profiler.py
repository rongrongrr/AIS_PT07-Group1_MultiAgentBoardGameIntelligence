"""Sequence-model profiler: classify a player's style from their move sequence.

Each move becomes a feature vector (what was taken, where it went, what it cost, whom it denied);
a small Transformer encoder (or GRU, for comparison) reads the whole sequence and predicts the
play-style archetype. Training uses random prefix truncation, so the model also works early in a
game, when only a few moves have been seen. Reasons for a prediction come from input-gradient
saliency: which per-move features pushed the predicted class most.

Trained on simulated self-play (scripts/train_sequence_profiler.py); labels on human games are
hypotheses, as with the feature-based classifier.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from tiles.ml.archetypes import COLORS, Prediction, WALL_COLORS

MAX_LEN = 48
MOVE_FEATURES = (
    [f"color_{c}" for c in COLORS]
    + ["from_center"]
    + [f"dest_row_{r + 1}" for r in range(5)] + ["dest_floor"]
    + ["pick_size", "overflow", "blocks_opponent", "repeats_own_color", "takes_token", "progress"]
)
D_IN = len(MOVE_FEATURES)
DEFAULT_SEQ_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "sequence_profiler.pt"


def _picked(board: dict, a: dict) -> int:
    if a["source_type"] == "factory":
        facs = board.get("factories", [])
        i = a.get("source_index")
        return sum(1 for t in facs[i] if t == a["color"]) if i is not None and i < len(facs) else 0
    return sum(1 for t in board.get("center_pool", []) if t == a["color"])


def move_vector(m: dict, player_name: str, t: int) -> np.ndarray:
    """Feature vector for one move (ledger/simulation format)."""
    a, board = m["action"], m["board"]
    v = np.zeros(D_IN, dtype=np.float32)
    v[COLORS.index(a["color"])] = 1.0
    v[5] = 1.0 if a["source_type"] == "center" else 0.0
    if a["destination"] == "floor":
        v[11] = 1.0
    else:
        v[6 + a["destination_row"]] = 1.0
    k = _picked(board, a)
    v[12] = min(1.0, k / 4.0)
    me = next((p for p in board.get("players", []) if p["name"] == player_name), None)
    if me is not None:
        if a["destination"] == "floor":
            v[13] = 1.0 if k else 0.0
        else:
            row = a["destination_row"]
            v[13] = min(1.0, max(0, k - ((row + 1) - len(me["pattern_lines"][row]))) / 4.0)
        held = any(a["color"] in line for line in me["pattern_lines"])
        if me.get("wall"):
            held = held or any(me["wall"][r][c] and WALL_COLORS[r][c] == a["color"]
                               for r in range(5) for c in range(5))
        v[15] = 1.0 if held else 0.0
    for opp in board.get("players", []):
        if opp["name"] != player_name and any(
                line and line[0] == a["color"] and len(line) < i + 1 for i, line in enumerate(opp["pattern_lines"])):
            v[14] = 1.0
            break
    v[16] = 1.0 if a["source_type"] == "center" and "firstPlayer" in board.get("center_pool", []) else 0.0
    v[17] = min(1.0, t / 30.0)
    return v


def sequence_matrix(moves: Sequence[dict], player_name: str) -> Optional[np.ndarray]:
    mine = [m for m in moves if m.get("player_name") == player_name and m.get("board")]
    if not mine:
        return None
    return np.stack([move_vector(m, player_name, t) for t, m in enumerate(mine[:MAX_LEN])])


def _torch():
    import torch
    import torch.nn as nn
    return torch, nn


def build_net(kind: str, n_classes: int, d: int = 48, layers: int = 2, heads: int = 4, dropout: float = 0.1):
    torch, nn = _torch()

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.kind = kind
            self.inp = nn.Linear(D_IN, d)
            self.pos = nn.Embedding(MAX_LEN, d)
            if kind == "transformer":
                layer = nn.TransformerEncoderLayer(d, heads, 2 * d, dropout, batch_first=True)
                self.enc = nn.TransformerEncoder(layer, layers)
            elif kind == "gru":
                self.enc = nn.GRU(d, d, batch_first=True)
            else:
                raise ValueError(kind)
            self.head = nn.Linear(d, n_classes)

        def forward(self, x, mask):                       # x: (B, L, D_IN); mask: (B, L) True = real move
            h = self.inp(x) + self.pos(torch.arange(x.shape[1], device=x.device))[None]
            if self.kind == "transformer":
                h = self.enc(h, src_key_padding_mask=~mask)
            else:
                h, _ = self.enc(h)
            m = mask.unsqueeze(-1).float()
            return self.head((h * m).sum(1) / m.sum(1).clamp(min=1.0))

    return Net()


def _batch(seqs: List[np.ndarray], mean: np.ndarray, std: np.ndarray):
    torch, _ = _torch()
    L = max(len(s) for s in seqs)
    x = np.zeros((len(seqs), L, D_IN), dtype=np.float32)
    mask = np.zeros((len(seqs), L), dtype=bool)
    for i, s in enumerate(seqs):
        x[i, : len(s)] = (s - mean) / std
        mask[i, : len(s)] = True
    return torch.from_numpy(x), torch.from_numpy(mask)


class SequenceProfiler:
    def __init__(self, kind: str = "transformer", classes: Optional[List[str]] = None, seed: int = 0):
        self.kind = kind
        self.classes = classes or []
        self.seed = seed
        self.net = None
        self.mean = np.zeros(D_IN, dtype=np.float32)
        self.std = np.ones(D_IN, dtype=np.float32)

    # ---- training -------------------------------------------------------------
    def fit(self, seqs: List[np.ndarray], labels: List[str], val: Optional[tuple] = None,
            epochs: int = 40, lr: float = 2e-3, batch: int = 64, min_prefix: int = 5) -> Dict[str, List[float]]:
        torch, nn = _torch()
        torch.manual_seed(self.seed)
        rng = random.Random(self.seed)
        self.classes = sorted(set(labels))
        y_all = np.array([self.classes.index(l) for l in labels], dtype=np.int64)
        cat = np.concatenate(seqs)
        self.mean, self.std = cat.mean(0), np.where(cat.std(0) < 1e-6, 1.0, cat.std(0))
        self.net = build_net(self.kind, len(self.classes))
        opt = torch.optim.AdamW(self.net.parameters(), lr=lr, weight_decay=1e-2)
        history = {"loss": [], "val_acc": []}
        n = len(seqs)
        for _ in range(epochs):
            self.net.train()
            order = list(range(n))
            rng.shuffle(order)
            total = 0.0
            for i in range(0, n, batch):
                idx = order[i:i + batch]
                chunk = []
                for j in idx:
                    s = seqs[j]
                    if rng.random() < 0.6 and len(s) > min_prefix:          # random prefix: learn to profile early
                        s = s[: rng.randint(min_prefix, len(s))]
                    chunk.append(s)
                x, mask = _batch(chunk, self.mean, self.std)
                logits = self.net(x, mask)
                loss = nn.functional.cross_entropy(logits, torch.from_numpy(y_all[idx]))
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.net.parameters(), 1.0)
                opt.step()
                total += float(loss) * len(idx)
            history["loss"].append(total / n)
            if val is not None:
                history["val_acc"].append(self.accuracy(*val))
        return history

    # ---- inference ------------------------------------------------------------
    def _probs(self, seqs: List[np.ndarray]) -> np.ndarray:
        torch, _ = _torch()
        self.net.eval()
        with torch.no_grad():
            x, mask = _batch(seqs, self.mean, self.std)
            return torch.softmax(self.net(x, mask), dim=-1).numpy()

    def predict_label(self, seq: np.ndarray) -> str:
        return self.classes[int(self._probs([seq])[0].argmax())]

    def accuracy(self, seqs: List[np.ndarray], labels: List[str], prefix: Optional[int] = None) -> float:
        if prefix:
            seqs = [s[:prefix] for s in seqs]
        probs = np.concatenate([self._probs(seqs[i:i + 256]) for i in range(0, len(seqs), 256)])
        pred = [self.classes[i] for i in probs.argmax(1)]
        return float(np.mean([p == t for p, t in zip(pred, labels)]))

    def predict(self, moves: Sequence[dict], player_name: str) -> Optional[Prediction]:
        seq = sequence_matrix(moves, player_name)
        if seq is None:
            return None
        torch, _ = _torch()
        probs = self._probs([seq])[0]
        best = int(probs.argmax())
        # saliency: gradient of the predicted logit w.r.t. the (standardised) input, per feature
        self.net.train(False)
        x, mask = _batch([seq], self.mean, self.std)
        x.requires_grad_(True)
        logit = self.net(x, mask)[0, best]
        logit.backward()
        sal = (x.grad * x).abs().mean(dim=(0, 1)).detach().numpy()
        top = np.argsort(-sal)[:3]
        reasons = [{"feature": MOVE_FEATURES[i], "importance": round(float(sal[i]), 4),
                    "meaning": f"moves like '{MOVE_FEATURES[i]}' drove this label"} for i in top]
        return Prediction(self.classes[best], round(float(probs[best]), 3),
                          {c: round(float(p), 3) for c, p in zip(self.classes, probs)}, reasons)

    # ---- persistence ----------------------------------------------------------
    def save(self, path: Path, meta: Optional[dict] = None) -> None:
        torch, _ = _torch()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        torch.save({"kind": self.kind, "classes": self.classes, "mean": self.mean, "std": self.std,
                    "state": self.net.state_dict(), "features": MOVE_FEATURES, "meta": meta or {}}, path)

    @classmethod
    def load(cls, path: Path) -> SequenceProfiler:
        torch, _ = _torch()
        blob = torch.load(path, map_location="cpu", weights_only=False)
        if blob["features"] != MOVE_FEATURES:
            raise ValueError("sequence model was trained with different move features; retrain it")
        p = cls(blob["kind"], blob["classes"])
        p.mean, p.std = blob["mean"], blob["std"]
        p.net = build_net(blob["kind"], len(blob["classes"]))
        p.net.load_state_dict(blob["state"])
        p.net.eval()
        return p
