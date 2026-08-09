"""Inference for "real player" bots: same two-CatBoost-model bridge as
behavior_clone.py's choose_bot_action, but for the ~20 real, individually-
identified players trained by train_player_profile_bots.py (profile_id +
that player's own vpip/pfr/af + causal session-position, instead of a
6-bucket archetype). See that file's docstring and
PokerDom_Microlimits_Analysis/scripts/select_player_profiles.py for how the
20 players were chosen and player_profile_seeds.csv for their real stats.

Deliberately a separate module rather than folded into behavior_clone.py:
different feature schema (profile_id instead of archetype, no
had_initiative-vs-archetype style bias -- the model itself learned each
individual's own tendencies directly from their real decisions, so there's
no separate "style multiplier" step here), and keeping it separate avoids
any risk of destabilizing choose_bot_action's extensively A/B-tested
mechanics. The monster-pot mitigations (progressive pot damping, repeated-
sizing downgrade, large-min-raise suppression) ARE reused verbatim -- those
are safety mechanisms independent of which model produced the base action,
and there's no reason to expect this smaller, player-specific model is
immune to the same failure mode.
"""

import math
import random
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
sys.path.insert(0, str(ANALYSIS_ROOT))

import pandas as pd
from catboost import CatBoostClassifier

from backend.bots.behavior_clone import (
    DOWNGRADE_REPEATED_SIZING,
    POT_DAMPING_FLOOR_FRAC,
    POT_DAMPING_FULL_BB,
    POT_DAMPING_START_BB,
    PROGRESSIVE_POT_DAMPING,
    RAISE_SUPPRESSION_MIN_INCREMENT_BB,
    RAISE_SUPPRESSION_POT_FRACTION,
    SUPPRESS_RAISE_WHEN_MIN_RAISE_LARGE,
    THINK_TIME_FOLD,
    THINK_TIME_OTHER,
    _n_prior_aggressive_actions_this_hand,
    _n_raises_this_street,
    _had_preflop_initiative,
    _seat_position,
)
from backend.engine.hand import Hand

if TYPE_CHECKING:
    from backend.dossier import SeatDossier

MODEL_DIR = Path(__file__).resolve().parents[2] / "data"
SEEDS_PATH = ANALYSIS_ROOT / "data" / "reference" / "player_profile_seeds.csv"

CAT_FEATURES = ["street", "position", "profile_id"]
NUMERIC_FEATURES = [
    "to_call_frac",
    "n_raises_this_street",
    "board_board_paired",
    "board_board_monotone",
    "board_board_two_tone",
    "board_board_max_suit_count",
    "board_board_connectedness",
    "board_board_high_card",
    "had_initiative",
    "player_vpip",
    "player_pfr",
    "player_af",
    "session_hands_so_far",
]
FEATURES = CAT_FEATURES + NUMERIC_FEATURES
STREET_BOARD_LEN = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}

_action_model = None
_sizing_model = None
_profiles_by_id: dict[str, dict] | None = None


def _load_models():
    global _action_model, _sizing_model
    if _action_model is None:
        _action_model = CatBoostClassifier()
        _action_model.load_model(str(MODEL_DIR / "player_profile_action.cbm"))
        _sizing_model = CatBoostClassifier()
        _sizing_model.load_model(str(MODEL_DIR / "player_profile_sizing.cbm"))
    return _action_model, _sizing_model


def load_profile_pool() -> dict[str, dict]:
    """{profile_id: {archetype, vpip, pfr, aggression_factor, hands_seen, ...}}
    -- the 20 real players available to seat as bots. Cached at module level
    (the seeds file doesn't change at runtime)."""
    global _profiles_by_id
    if _profiles_by_id is None:
        seeds = pd.read_csv(SEEDS_PATH)
        _profiles_by_id = {
            row["profile_id"]: {
                "player": row["player"],
                "archetype": row["archetype"],
                "vpip": float(row["vpip"]),
                "pfr": float(row["pfr"]),
                "aggression_factor": float(row["aggression_factor"]),
                "hands_seen": int(row["hands_seen"]),
                "n_sessions": int(row["n_sessions"]),
            }
            for _, row in seeds.iterrows()
        }
    return _profiles_by_id


def _build_features(hand: Hand, seat: int, profile_id: str, session_hands_so_far: int) -> dict:
    from src.pipeline.board_texture import texture_features  # noqa: E402  (path inserted above)

    profile = load_profile_pool()[profile_id]
    legal = hand.legal_actions(seat)
    pot_before = sum(p.total_contributed for p in hand.players.values())
    board_len = STREET_BOARD_LEN[hand.street]
    texture = texture_features(hand.board[:board_len])

    return {
        "street": hand.street,
        "position": _seat_position(hand, seat),
        "profile_id": profile_id,
        "to_call_frac": (legal["call_amount"] / pot_before) if pot_before > 0 else 0.0,
        "n_raises_this_street": _n_raises_this_street(hand),
        "had_initiative": int(_had_preflop_initiative(hand, seat)),
        "player_vpip": profile["vpip"],
        "player_pfr": profile["pfr"],
        "player_af": profile["aggression_factor"],
        "session_hands_so_far": session_hands_so_far,
        **{f"board_{k}": v for k, v in texture.items()},
    }


def choose_player_profile_action(
    hand: Hand,
    seat: int,
    profile_id: str,
    session_hands_so_far: int,
    seed: int | None = None,
) -> tuple[str, float | None]:
    """Same shape/contract as behavior_clone.choose_bot_action: returns
    (action, amount) ready for Hand.apply_action. `session_hands_so_far`
    should be the same live counter TableTurnover/SeatOccupant already
    tracks (hands_played) -- see build_player_profile_training_data.py's
    docstring for why that's deliberately the same causal quantity used at
    training time."""
    action_model, sizing_model = _load_models()
    rng = random.Random(seed)

    features = _build_features(hand, seat, profile_id, session_hands_so_far)
    legal = hand.legal_actions(seat)

    row = [[features[f] for f in FEATURES]]
    proba = dict(zip(action_model.classes_, action_model.predict_proba(row)[0]))

    can_check = legal["can_check"]
    allowed = {"folds": True, "checks": can_check, "calls": not can_check, "bets": not can_check, "raises": False}
    if can_check:
        allowed["raises"] = legal["max_raise_to"] > legal["min_raise_to"] - 1
        allowed["bets"] = True
        allowed["calls"] = False
    else:
        allowed["bets"] = False
        allowed["raises"] = legal["max_raise_to"] > 0

    if SUPPRESS_RAISE_WHEN_MIN_RAISE_LARGE and allowed.get("raises"):
        pot_before_for_cap = sum(p.total_contributed for p in hand.players.values())
        min_raise_increment_bb = hand.min_raise / hand.big_blind
        pot_bb = pot_before_for_cap / hand.big_blind
        if min_raise_increment_bb > max(RAISE_SUPPRESSION_MIN_INCREMENT_BB, RAISE_SUPPRESSION_POT_FRACTION * pot_bb):
            allowed["raises"] = False

    filtered = {a: p for a, p in proba.items() if allowed.get(a, False) and p > 0}
    if not filtered:
        return ("check" if can_check else "fold"), None

    total = sum(filtered.values())
    r = rng.random() * total
    acc = 0.0
    chosen = next(iter(filtered))
    for a, p in filtered.items():
        acc += p
        if r <= acc:
            chosen = a
            break

    if chosen == "folds":
        return "fold", None
    if chosen == "checks":
        return "check", None
    if chosen == "calls":
        return "call", None

    size_proba = dict(zip(sizing_model.classes_, sizing_model.predict_proba(row)[0]))
    bucket = max(size_proba, key=size_proba.get)

    BUCKET_DOWNGRADE = {"large": "medium", "medium": "small", "small": "small"}
    if DOWNGRADE_REPEATED_SIZING:
        n_prior_aggressive = _n_prior_aggressive_actions_this_hand(hand, seat)
        for _ in range(min(n_prior_aggressive, 2)):
            bucket = BUCKET_DOWNGRADE[bucket]

    pot_before = sum(p.total_contributed for p in hand.players.values())
    frac_by_bucket = {"small": 0.3, "medium": 0.55, "large": 0.9}
    effective_frac = frac_by_bucket[bucket]

    if PROGRESSIVE_POT_DAMPING:
        pot_bb = pot_before / hand.big_blind
        if pot_bb > POT_DAMPING_START_BB:
            damp_progress = min(1.0, (pot_bb - POT_DAMPING_START_BB) / (POT_DAMPING_FULL_BB - POT_DAMPING_START_BB))
            effective_frac = effective_frac * (1 - damp_progress) + POT_DAMPING_FLOOR_FRAC * damp_progress

    raw_amount = effective_frac * max(pot_before, hand.big_blind)
    target = hand.current_bet + max(raw_amount, hand.min_raise)
    amount = max(legal["min_raise_to"], min(target, legal["max_raise_to"]))

    verb = "bet" if chosen == "bets" else "raise"
    final_amount = round(amount, 2)
    if final_amount < legal["min_raise_to"]:
        final_amount = min(math.ceil(legal["min_raise_to"] * 100) / 100, legal["max_raise_to"])
    return verb, final_amount


def player_profile_think_time(action: str) -> float:
    return THINK_TIME_FOLD if action == "fold" else THINK_TIME_OTHER
