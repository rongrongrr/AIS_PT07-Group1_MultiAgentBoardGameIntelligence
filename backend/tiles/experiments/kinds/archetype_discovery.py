"""Archetype discovery (A4): are the 3–5 archetypes recoverable?

Plays games with five distinct greedy weight presets (blocker,
collector, risk_taker, cautious, vanilla), profiles the subject with a
fresh BasicProfiler per game, and asks two questions of the resulting
trait vectors:

* **unsupervised** — does k-means (pure Python) recover the presets as
  clusters? Reported as cluster purity.
* **rule-based** — does the archetype classifier map each preset to its
  intended archetype? Reported as a preset × archetype confusion matrix
  and an agreement rate.
"""

from __future__ import annotations

import random
from typing import Dict, List

from tiles.agents.base import DecisionContext
from tiles.agents.profiler import ARCHETYPES, BasicProfiler, KMeans
from tiles.agents.profiler.archetypes import standardize
from tiles.agents.tacticians.greedy import GreedyTactician
from tiles.agents.tacticians.heuristics import DEFAULT_WEIGHTS
from tiles.core import deal_round, legal_actions, new_game, step
from tiles.experiments.registry import ExperimentSpec, ParamSpec
from tiles.sim.prediction_eval import BLOCKER_WEIGHTS, COLLECTOR_WEIGHTS, _scaled

from ._common import abort_note, bar, matrix, pct, result, table

TRAIT_KEYS = (
    "color_bias",
    "center_rate",
    "floor_rate",
    "completion_rate",
    "denial_avg",
    "risk_avg",
    "bonus_focus",
    "fpt_rate",
    "immediate_avg",
)

#: Greedy weight presets, each a caricature of one archetype.
PRESETS: Dict[str, Dict[str, float]] = {
    "blocker": BLOCKER_WEIGHTS,
    "collector": COLLECTOR_WEIGHTS,
    "risk_taker": _scaled(
        DEFAULT_WEIGHTS, floor_penalty=0.15, first_player=5.0,
        immediate_points=0.8, denial=1.5,
    ),
    "cautious": _scaled(
        DEFAULT_WEIGHTS, floor_penalty=4.0, denial=0.1,
        near_completion=1.5, first_player=0.3,
    ),
    "vanilla": dict(DEFAULT_WEIGHTS),
}

#: The archetype each preset is designed to evoke.
EXPECTED_ARCHETYPE = {
    "blocker": "aggressive_blocker",
    "collector": "set_collector",
    "risk_taker": "risk_taker",
    "cautious": "cautious_optimizer",
    "vanilla": "greedy_scorer",
}


def _play_and_profile(weights: Dict[str, float], seat: int, seed: int):
    """One 2-player game, subject at ``seat`` vs vanilla greedy; returns
    the subject's PlayerProfile from a fresh profiler."""
    subject = GreedyTactician(weights)
    opponent = GreedyTactician(DEFAULT_WEIGHTS)
    tacticians = [opponent, opponent]
    tacticians[seat] = subject
    profiler = BasicProfiler()
    names = ["opponent", "opponent"]
    names[seat] = "subject"
    state = new_game(2, seed=seed, player_names=names)
    rng = random.Random(seed)
    while not state.is_game_over:
        mover = state.current_player
        legal = legal_actions(state)
        decision = tacticians[mover].decide(
            DecisionContext(state=state, player_index=mover, legal=legal)
        )
        before = state.clone()
        move, round_result = step(state, decision.action)
        profiler.observe(before, decision.action, move)
        if round_result is not None and not round_result.game_over:
            deal_round(state, rng)
    return profiler.profile(seat)


def run(params: dict, ctx) -> dict:
    games_per_preset = params["games_per_preset"]
    seed = params["seed"]
    presets = list(PRESETS)
    archetypes = list(ARCHETYPES)
    total = games_per_preset * len(presets)

    samples: List[dict] = []
    done = 0
    for pi, preset in enumerate(presets):
        for g in range(games_per_preset):
            if ctx.stopped():
                break
            game_seed = seed * 1000 + pi * 100 + g
            profile = _play_and_profile(PRESETS[preset], g % 2, game_seed)
            samples.append(
                {
                    "preset": preset,
                    "archetype": profile.archetype,
                    "confidence": round(profile.confidence, 3),
                    "traits": {k: round(profile.traits.get(k, 0.0), 4) for k in TRAIT_KEYS},
                    "moves_observed": profile.moves_observed,
                }
            )
            done += 1
            ctx.progress(done, total, f"{preset}: game {g + 1}/{games_per_preset} -> {profile.archetype}")
        if ctx.stopped():
            break

    # Rule-based classifier: preset x archetype confusion.
    confusion = {p: {a: 0 for a in archetypes} for p in presets}
    agree = 0
    for s in samples:
        confusion[s["preset"]][s["archetype"]] += 1
        agree += int(s["archetype"] == EXPECTED_ARCHETYPE[s["preset"]])
    agreement = agree / len(samples) if samples else 0.0

    # Unsupervised: k-means over trait vectors.
    k = max(1, min(params["k"], len(samples)))
    cluster_matrix = {p: [0] * k for p in presets}
    purities: List[float] = []
    cluster_majority: List[str] = []
    purity = 0.0
    if samples:
        # Standardize so every trait counts equally, then keep the best of
        # several k-means++ restarts (lowest within-cluster inertia).
        vectors = standardize(
            [[s["traits"][key] for key in TRAIT_KEYS] for s in samples]
        )
        best_km, best_inertia = None, float("inf")
        for restart in range(10):
            candidate = KMeans().fit(vectors, k=k, seed=seed * 10 + restart)
            inertia = sum(
                KMeans._dist2(v, candidate.centroids[candidate.predict(v)])
                for v in vectors
            )
            if inertia < best_inertia:
                best_km, best_inertia = candidate, inertia
        km = best_km
        labels = [km.predict(v) for v in vectors]
        for s, label in zip(samples, labels):
            s["cluster"] = label
            cluster_matrix[s["preset"]][label] += 1
        majority_total = 0
        for c in range(k):
            counts = {p: cluster_matrix[p][c] for p in presets}
            size = sum(counts.values())
            if size == 0:
                purities.append(0.0)
                cluster_majority.append("-")
                continue
            best = max(counts, key=counts.get)
            majority_total += counts[best]
            purities.append(counts[best] / size)
            cluster_majority.append(best)
        purity = majority_total / len(samples)

    summary = (
        f"Over {len(samples)} profiled games, k-means (k={k}) recovered the presets with "
        f"{pct(purity)} cluster purity; the rule-based classifier assigned the intended "
        f"archetype in {pct(agreement)} of games."
    )
    return result(
        summary=abort_note(ctx) + summary,
        metrics={
            "n_games": len(samples),
            "purity": purity,
            "classifier_agreement": agreement,
            "k": k,
        },
        tables=[
            table(
                "Preset x archetype (rule-based classifier)",
                ["preset", "expected"] + archetypes,
                [[p, EXPECTED_ARCHETYPE[p]] + [confusion[p][a] for a in archetypes]
                 for p in presets],
            ),
            table(
                "Clusters",
                ["cluster", "size", "majority preset", "purity"],
                [[c, sum(cluster_matrix[p][c] for p in presets), cluster_majority[c], round(purities[c], 3)]
                 for c in range(len(purities))],
            ),
            table(
                "Samples",
                ["preset", "archetype", "confidence", "cluster"] + list(TRAIT_KEYS),
                [[s["preset"], s["archetype"], s["confidence"], s.get("cluster", "-")]
                 + [s["traits"][key] for key in TRAIT_KEYS] for s in samples],
            ),
        ],
        series=[
            matrix("Preset x archetype (rule-based)", presets, archetypes,
                   [[confusion[p][a] for a in archetypes] for p in presets],
                   x_label="classified as", y_label="preset"),
            matrix("Preset x cluster (k-means)", presets, [f"c{c}" for c in range(k)],
                   [cluster_matrix[p] for p in presets],
                   x_label="cluster", y_label="preset"),
            bar("Cluster purity", [f"c{c}" for c in range(len(purities))],
                {"purity": purities}, x_label="cluster", y_label="purity"),
        ],
        raw={"samples": samples, "presets": {p: PRESETS[p] for p in presets},
             "expected": EXPECTED_ARCHETYPE, "params": dict(params)},
    )


SPEC = ExperimentSpec(
    name="archetype_discovery",
    title="Archetype discovery",
    description=(
        "Can the player archetypes be recovered from behavior? Profiles "
        "games played by five distinct weight presets, clusters the trait "
        "vectors with k-means, and checks the rule-based classifier's "
        "preset-to-archetype confusion."
    ),
    report_section="4. Opponent modeling & profiling (A4)",
    estimated="~20 s at defaults",
    params=(
        ParamSpec("games_per_preset", "int", 3, "Games per weight preset", 1, 100),
        ParamSpec("seed", "int", 0, "Base random seed", 0, 1_000_000),
        ParamSpec("k", "int", 5, "Number of k-means clusters", 1, 10),
    ),
    run=run,
)
