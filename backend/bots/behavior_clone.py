"""Bot inference: loads the two trained CatBoost models (action type, sizing)
and samples a live action from the current Hand state -- the actual bridge
between Phase C's training and real gameplay.

Samples from the predicted probability distribution rather than argmax: an
always-argmax bot is deterministic and immediately readable/exploitable, and
doesn't match how the real population it was trained on actually plays (real
players are stochastic given the same stat line).
"""

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
sys.path.insert(0, str(ANALYSIS_ROOT))

from catboost import CatBoostClassifier

from backend.engine.hand import Hand
from src.pipeline.board_texture import texture_features

MODEL_DIR = Path(__file__).resolve().parents[2] / "data"

CAT_FEATURES = ["street", "position", "archetype"]
# 2026-07-30: stack_bb/spr were added then reverted here -- see
# train_behavior_clone.py's NUMERIC_FEATURES comment for the full story
# (measured regression, not just "no improvement"). Must match that file's
# feature list exactly, since both load the same saved .cbm models.
NUMERIC_FEATURES = [
    "to_call_frac",
    "n_raises_this_street",
    "board_board_paired",
    "board_board_monotone",
    "board_board_two_tone",
    "board_board_max_suit_count",
    "board_board_connectedness",
    "board_board_high_card",
]
FEATURES = CAT_FEATURES + NUMERIC_FEATURES

STREET_BOARD_LEN = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}

# 2026-07-30: two separate attempts to curb the ~19% "monster pot" (>50bb)
# rate were tried and both reverted -- neither moved the incidence at all:
#   1. A per-player stack-relative cap (shove if leaving an awkward tiny
#      stack): measured WORSE (non-monster-pot bb/100 dropped from +12-14 to
#      +6-7), monster-pot rate unchanged.
#   2. A pot-relative cap (dampen bet sizing once the shared pot itself
#      already exceeds 50bb, gating on both the pot as it stands and the
#      *projected* pot after the bet gets called, to catch a single big
#      raise that leaps straight past the threshold): monster-pot rate moved
#      19.06% -> 18.77% -> 19.24% across variants -- all within noise,
#      bb/100 unchanged (+15.05 -> +15.54 -> +14.32, all within the ~2.7 CI).
# Conclusion: the monster-pot rate isn't an artifact of single-street sizing
# escalation at all (that's what both caps targeted) -- it's more likely
# structural (multiway pots where many modest bets across several streets
# simply add up, or legitimate all-in confrontations at 200bb starting
# stacks). Not revisiting this specific "cap the bet size" approach again
# without a new hypothesis for the actual cause.

# how long the bot "thinks" before acting, per the user's spec (folds are fast,
# everything else takes closer to a second) -- not model-driven, a simple rule.
THINK_TIME_FOLD = 0.5
THINK_TIME_OTHER = 1.0

_action_model = None
_sizing_model = None


def _load_models():
    global _action_model, _sizing_model
    if _action_model is None:
        _action_model = CatBoostClassifier()
        _action_model.load_model(str(MODEL_DIR / "behavior_clone_action.cbm"))
        _sizing_model = CatBoostClassifier()
        _sizing_model.load_model(str(MODEL_DIR / "behavior_clone_sizing.cbm"))
    return _action_model, _sizing_model


_POSITION_LABELS = {
    2: ("BTN", "BB"),
    3: ("BTN", "SB", "BB"),
    4: ("BTN", "SB", "BB", "UTG"),
    5: ("BTN", "SB", "BB", "UTG", "CO"),
    6: ("BTN", "SB", "BB", "UTG", "MP", "CO"),
    7: ("BTN", "SB", "BB", "UTG", "MP", "MP+1", "CO"),
    8: ("BTN", "SB", "BB", "UTG", "UTG+1", "MP", "MP+1", "CO"),
}


def _seat_position(hand: Hand, seat: int) -> str:
    order = hand._active_seats_from_button()
    labels = _POSITION_LABELS.get(len(order), _POSITION_LABELS[8][: len(order)])
    try:
        return labels[order.index(seat)]
    except ValueError:
        return "MP"


def _n_raises_this_street(hand: Hand) -> int:
    return sum(1 for a in hand.actions if a.street == hand.street and a.action == "raises")


def _build_features(hand: Hand, seat: int, archetype: str) -> dict:
    player = hand.players[seat]
    legal = hand.legal_actions(seat)
    pot_before = sum(p.total_contributed for p in hand.players.values())
    board_len = STREET_BOARD_LEN[hand.street]
    texture = texture_features(hand.board[:board_len])

    return {
        "street": hand.street,
        "position": _seat_position(hand, seat),
        "archetype": archetype,
        "to_call_frac": (legal["call_amount"] / pot_before) if pot_before > 0 else 0.0,
        "n_raises_this_street": _n_raises_this_street(hand),
        **{f"board_{k}": v for k, v in texture.items()},
    }


def choose_bot_action(hand: Hand, seat: int, archetype: str = "TAG", seed: int | None = None) -> tuple[str, float | None]:
    """Returns (action, amount) ready to pass to Hand.apply_action. `amount` is
    None for fold/check/call."""
    action_model, sizing_model = _load_models()
    rng = random.Random(seed)

    features = _build_features(hand, seat, archetype)
    legal = hand.legal_actions(seat)

    row = [[features[f] for f in FEATURES]]
    proba = dict(zip(action_model.classes_, action_model.predict_proba(row)[0]))

    # mask out actions that aren't legal right now, renormalize
    can_check = legal["can_check"]
    allowed = {
        "folds": True,
        "checks": can_check,
        "calls": not can_check,
        "bets": not can_check,
        "raises": can_check is False and legal["max_raise_to"] > 0,
    }
    # if facing a bet, "bets" isn't legal (that's a raise); if not facing one, "raises" isn't legal
    if can_check:
        allowed["raises"] = legal["max_raise_to"] > legal["min_raise_to"] - 1
        allowed["bets"] = True
        allowed["calls"] = False
    else:
        allowed["bets"] = False
        allowed["raises"] = legal["max_raise_to"] > 0

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

    # bets/raises: sample a size bucket, then a concrete amount within it
    size_proba = dict(zip(sizing_model.classes_, sizing_model.predict_proba(row)[0]))
    bucket = max(size_proba, key=size_proba.get)
    pot_before = sum(p.total_contributed for p in hand.players.values())
    frac_by_bucket = {"small": 0.3, "medium": 0.55, "large": 0.9}
    raw_amount = frac_by_bucket[bucket] * max(pot_before, hand.big_blind)
    target = hand.current_bet + max(raw_amount, hand.min_raise)
    amount = max(legal["min_raise_to"], min(target, legal["max_raise_to"]))

    verb = "bet" if chosen == "bets" else "raise"
    return verb, round(amount, 2)


def bot_think_time(action: str) -> float:
    return THINK_TIME_FOLD if action == "fold" else THINK_TIME_OTHER
