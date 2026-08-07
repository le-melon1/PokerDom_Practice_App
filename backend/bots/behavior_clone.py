"""Bot inference: loads the two trained CatBoost models (action type, sizing)
and samples a live action from the current Hand state -- the actual bridge
between Phase C's training and real gameplay.

Samples from the predicted probability distribution rather than argmax: an
always-argmax bot is deterministic and immediately readable/exploitable, and
doesn't match how the real population it was trained on actually plays (real
players are stochastic given the same stat line).

## Monster-pot fix (2026-08-07) -- three earlier attempts (two in a prior
session, one earlier today) all measured as ~no effect on the documented
~22-24% monster-pot (>50bb) rate. This time, diagnosed with real hand logs
before touching code, not guessed:

  - Pulled 662 real monster pots from a batch. **100% were multiway (3+
    contributors), 0% heads-up.** The dominant mechanism is a raise war
    among several DIFFERENT players (real example: 4 seats re-raising
    preflop, $7 -> $32 -> $107) -- no single player repeats, so a per-player
    history check can't see it coming.
  - First mechanism, DOWNGRADE_REPEATED_SIZING (downgrades a player's OWN
    bet-size bucket after they've already bet/raised earlier THIS HAND, any
    street): measured ~no effect (24.4% monster-pot rate) -- confirmed why:
    it can only catch the SAME player escalating across streets, and the
    real driver is DIFFERENT players escalating within one street.
  - Second mechanism, PROGRESSIVE_POT_DAMPING (shrinks the bet-size fraction
    as the current pot, in bb, grows past a threshold -- applies to every
    bettor, not just repeat offenders): with gentle params (start 15bb, full
    60bb) also measured ~no effect. Root cause: `Hand.min_raise`
    (backend/engine/hand.py) locks in at the size of the LAST full raise's
    increment, and every subsequent raise is legally bound to be at least
    that big -- `max(raw_amount, hand.min_raise)` floors any damped size
    back up once a raise war is already underway. Sizing alone cannot stop
    a raise war in progress.
  - Third mechanism, SUPPRESS_RAISE_WHEN_MIN_RAISE_LARGE: since sizing can't
    fix an in-progress war, this drops "raises" from the legal-action set
    entirely once the legal min-raise increment is already large (>= a flat
    8bb floor AND >= 40% of the current pot) -- forces a call-or-fold choice
    instead of compounding further.
  - Shipped all three together (PROGRESSIVE_POT_DAMPING tightened to start
    8bb/full 30bb/floor 0.08 after the gentle version underperformed).
    Measured on 80k hands, same seed as the pre-fix baseline: monster-pot
    rate **22-24% -> 19.99-20.04%** (real, ~3-4pp, consistent across a
    3000-hand diagnostic and the full 80k run) -- the first attempt across
    four total (two prior + two of today's own) that moved this number at
    all. bb/100 excluding monster pots was NOT measurably hurt (+12.04 with
    rake / +24.38 without, in the same range as recent unrelated runs).
  - **Honest limit (as of that point): this was a partial fix, not a full
    one.** ~20% of hands still balloon past 50bb.

## Monster-pot fix, follow-up (2026-08-07 pm) -- the ~20% residual was
diagnosed with real hand-classification this time (scripts/diagnose_
monster_pots.py, 40k hands), not guessed. The "bet+call, no raise" theory
above turned out wrong: multiway calling was only 1.4% of remaining monster
pots. The actual breakdown: 84.9% "moderate_raising" (1-2 raises per street,
but escalating across SEVERAL streets -- each individual raise legal and
unremarkable, cumulative total still >50bb) vs 13.7% real raise wars (3+
raises one street) vs 1.4% multiway calling. SUPPRESS_RAISE_WHEN_MIN_RAISE_
LARGE only engages once the min-raise increment ITSELF is already large
relative to pot -- moderate one-raise-per-street-across-many-streets growth
never trips that bar. Tried tightening PROGRESSIVE_POT_DAMPING instead
(start 8bb->5bb, full 30bb->18bb, floor 0.08->0.05 -- same mechanism, just
biting earlier and harder, since it already applies pot-wide regardless of
street). Measured on 80k hands, same seed: monster-pot rate **19.87% ->
12.02%/11.82%** (with/without rake) -- a real ~8pp drop, not noise (SE for a
rate this size at n=80000 is ~0.14pp). bb/100 excl. monster pots ALSO
improved substantially in the same run: +21.78 -> +61.30 with rake (CI
+/-3.05 vs +/-3.98, non-overlapping), +35.33 -> +78.04 without rake (CI
+/-3.31 vs +/-4.31) -- no rate-vs-magnitude tradeoff here, both moved the
right direction together. Shipped the tighter thresholds (values above
already updated). Mechanism mix among the smaller remaining pool shifted
toward real raise wars (13.7% -> 24.3% of a shrunk total) -- the "moderate
escalation" bucket is what actually got squeezed.
  - **Still an honest partial fix**, not zero: ~12% of hands still exceed
    50bb, and at this table's 100bb effective stack depth, some real
    fraction of that is probably legitimate deep-stack variance (two big
    hands colliding, valuebet-called down three streets) rather than a bug
    -- the >50bb threshold was always a coarse proxy, not a strict bug
    definition. If revisited: the true missing feature is still genuine
    stack-depth awareness (v1 retraining attempt with stack_bb/spr features
    measured WORSE, see train_behavior_clone.py's NUMERIC_FEATURES comment).

## Monster-pot fix, third pass (2026-08-07 pm, same session) -- tightened
SUPPRESS_RAISE_WHEN_MIN_RAISE_LARGE too (min increment 8bb->5bb, pot fraction
0.4->0.25), even though the diagnosis above showed real raise wars are now
the SMALLER remaining slice (13.7% of the shrunk pool) -- worth checking
since it's the one mechanism untouched by the second pass. Measured on 80k
hands, same seed, against the tightened-damping baseline above (12.02%/
11.82%, +61.30/+78.04): monster-pot rate 12.02%/11.82% -> **11.14%/11.09%**
-- a real further drop (SE at this rate/n is ~0.11pp, the ~0.8pp move is
several SE, not noise) confirmed by the diagnostic script too (12.16% ->
11.25%, mechanism mix barely shifted: moderate_raising still 79.7% of the
smaller remaining pool). bb/100 excl. monster pots was flat within noise
both directions (+61.30->+63.57 with rake, +78.04->+77.03 without -- both
deltas inside the combined CI). Net: real small win on the rate, no cost --
kept. Mechanism mix confirms "moderate multi-street escalation" is now
solidly the dominant remaining category and the productive next lever if
this is revisited again, not raise-war suppression (already tightened twice)
or multiway-calling (never was the real driver, see above).

## had_initiative feature, and a real training/serving skew bug (2026-08-08,
overnight, unattended per user's request to keep testing hypotheses and
improving the player models). Motivation: the ML bots have never known
whether THEY had preflop initiative when deciding how to act, despite
abc_bot.py's own v17 DONK_BLUFF_VS_TIGHT exploit existing precisely because
real tight archetypes fold more to a donk lead than an equally-sized
continuation bet -- a model that can't represent "I'm continuation betting"
vs. "I'm donk-leading" can't learn that distinction from either side either.

First attempt computed the feature (was this player the last preflop
raiser) ONCE per hand from the FULL preflop action sequence, hindsight-style,
and applied it to every row uniformly. That trains on information not
available at decision time: a player who opens and later gets 3-bet would
have their own OPENING-raise row retroactively labeled had_initiative=False,
since by hand's end someone else is the final raiser -- info they couldn't
have had yet. Live inference (_had_preflop_initiative, added alongside this
feature) is correctly causal (only sees hand.actions accumulated SO FAR), so
training and serving disagreed. This wasn't caught by the held-out-loss
check (which measured a suspiciously large 25% relative improvement, 0.67520
-> 0.50469) -- it was caught by the DOWNSTREAM bot-vs-bot simulation:
hero's own PFR jumped 14.8% -> 17.1% and win-rate-by-hand 15.7% -> 20.0%
despite zero changes to hero's own decision logic, which is the kind of
"too good to be true" number this file's own history (2026-07-30's stack_bb/
spr episode, the 4th monster-pot refinement, v19's premium sizing) says to
distrust rather than ship. Root-caused to the hindsight leak, fixed by
tracking the running preflop last-raiser incrementally during the same
sequential replay build_training_data.py already does (updated only AFTER
each row is recorded, exactly matching live inference's causal ordering).
Sanity-confirmed the fix: had_initiative is now identically 0.0 for every
PREFLOP row (provably always true -- you can't be mid-decision while still
being your own hand's most recent raiser, since action only returns to a
raiser if someone else acted first, which would make THEM the most recent
raiser) and varies 18.9-19.4% True on each postflop street, exactly the
shape intended.

Re-measured on the corrected data (same 1M-row held-out split as before):
held-out loss improvement is real but far more modest than the leaky
version suggested -- action model 0.67520 -> 0.66922 (was 0.50469 pre-fix),
sizing model 0.59720 -> 0.59090 (barely changed by the fix, this model was
less affected by the leak). Retrained the shipped .cbm models on the
corrected data. Downstream, 80k hands same seed: hero VPIP/PFR 17.6%/15.3%
(back in the normal ~17-18%/~15% range, not the leaky version's inflated
17%), bb/100 excl. monster pots flat within noise both ways (+64.09 vs
+63.57 with rake, +75.58 vs +77.03 without -- CIs overlap). One real,
disclosed side effect: monster-pot rate rose 11.14%/11.09% -> 12.68%/12.72%
(a genuine ~1.5-1.6pp move, several times the ~0.11pp SE at this n, not
noise) -- plausible mechanism: a model that can now correctly represent how
much MORE aggressive real players are with initiative (72.5% aggressive
action rate vs. 8.1% without, see the raw split in this feature's
NUMERIC_FEATURES comment) predicts raises more confidently in continuation-
bet spots specifically, and more raises happening at all gives the
"moderate multi-street escalation" mechanism (still 82.8% of monster pots)
more chances to compound, even though each individual raise is still
correctly damped/sized. Shipped anyway: this is a genuine, measured realism
improvement (the explicit ask), the monster-pot rate is still far below the
original 20-24% baseline, and bb/100 wasn't measurably hurt -- but it's a
real tradeoff, not a free win, and worth knowing about if the monster-pot
rate is revisited again.

Immediate follow-up, same night: since the regression above was traced to
the new model raising more confidently (not to the damping/suppression
mechanisms themselves weakening), retightened RAISE_SUPPRESSION_MIN_
INCREMENT_BB (5bb->4bb) and RAISE_SUPPRESSION_POT_FRACTION (0.25->0.2) to
compensate, without touching PROGRESSIVE_POT_DAMPING. Recovered most of the
regression: monster-pot rate 12.68%/12.72% -> 11.52%/11.37% (close to the
pre-had_initiative 11.14%/11.09%, a small ~0.3-0.4pp residual remains),
bb/100 excl. monster pots unchanged within noise both directions (+64.09 ->
+62.06 with rake, +75.58 -> +81.31 without -- both deltas inside the
combined CI). Kept -- recovers most of the cost of the realism gain at no
measurable cost of its own.
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
# 2026-08 (v2 retrain, tested against the FEATURES-without-had_initiative
# baseline below): the ML bots have never known whether THEY had preflop
# initiative when deciding how to act -- despite abc_bot.py's own v17
# DONK_BLUFF_VS_TIGHT exploit existing because real tight archetypes fold
# more to a donk lead than an equally-sized cbet. A model that can't tell
# "I'm continuation betting" from "I'm donk-leading" can't learn that
# distinction either way. Same definition as decision_points.py's
# bettor_had_initiative / abc_bot.py's _had_preflop_initiative: was this
# player the last preflop raiser in the hand.
HAD_INITIATIVE_FEATURE = True  # corrected causal retrain, 2026-08-08
# were trained without this feature; predict_proba requires an exact feature-schema match.
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
if HAD_INITIATIVE_FEATURE:
    NUMERIC_FEATURES = NUMERIC_FEATURES + ["had_initiative"]
FEATURES = CAT_FEATURES + NUMERIC_FEATURES

STREET_BOARD_LEN = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}

# see choose_bot_action's BUCKET_DOWNGRADE comment -- flip False to A/B-test
# the monster-pot fix against the pre-fix baseline.
DOWNGRADE_REPEATED_SIZING = True

# see choose_bot_action's PROGRESSIVE_POT_DAMPING comment -- the mechanism
# that actually targets multiway raise wars (confirmed to be 100% of real
# monster pots sampled, vs. 0% heads-up). Flip False to A/B-test.
PROGRESSIVE_POT_DAMPING = True
POT_DAMPING_START_BB = 5.0
POT_DAMPING_FULL_BB = 18.0
POT_DAMPING_FLOOR_FRAC = 0.05
# Tried (2026-08-07): scaling the damping start point earlier per extra live
# opponent, on the theory that a "large" bet costs the pot more per street
# when several players call it. Measured no further improvement over the
# flat version (20.54% vs 20.04% monster-pot rate, within noise for the
# sample sizes tested) -- reverted rather than ship unproven complexity.
# If revisited, test with a bigger sample before concluding either way.

# see choose_bot_action's SUPPRESS_RAISE_WHEN_MIN_RAISE_LARGE comment -- the
# mechanism that actually stops an in-progress raise war (sizing alone can't,
# since Hand.min_raise floors any damped amount back up). Suppresses only
# once the legal min-raise increment is BOTH >= a flat floor (small early-
# hand raises are never touched) AND large relative to the current pot.
SUPPRESS_RAISE_WHEN_MIN_RAISE_LARGE = True
RAISE_SUPPRESSION_MIN_INCREMENT_BB = 4.0
RAISE_SUPPRESSION_POT_FRACTION = 0.2

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


def _had_preflop_initiative(hand: Hand, seat: int) -> bool:
    """Same definition as abc_bot.py's own helper of the same name and
    decision_points.py's bettor_had_initiative -- was this seat the last
    preflop raiser in the hand."""
    preflop_raises = [a for a in hand.actions if a.street == "preflop" and a.action == "raises"]
    return bool(preflop_raises) and preflop_raises[-1].seat == seat


def _n_prior_aggressive_actions_this_hand(hand: Hand, seat: int) -> int:
    """Bets/raises by THIS seat across the whole hand so far (any street) --
    see BUCKET_DOWNGRADE below for why this matters and n_raises_this_street
    (which resets every street) can't substitute for it."""
    return sum(1 for a in hand.actions if a.seat == seat and a.action in ("bets", "raises"))


def _style_bias(archetype: str) -> dict[str, float]:
    archetype = archetype or "TAG"
    if archetype in {"Maniac", "LAG"}:
        return {"folds": 0.7, "checks": 1.0, "calls": 1.1, "bets": 1.4, "raises": 1.3}
    if archetype in {"Nit", "TAG"}:
        return {"folds": 1.1, "checks": 1.0, "calls": 1.0, "bets": 0.95, "raises": 0.9}
    return {"folds": 1.0, "checks": 1.0, "calls": 1.05, "bets": 1.05, "raises": 1.05}


def _build_features(hand: Hand, seat: int, archetype: str) -> dict:
    player = hand.players[seat]
    legal = hand.legal_actions(seat)
    pot_before = sum(p.total_contributed for p in hand.players.values())
    board_len = STREET_BOARD_LEN[hand.street]
    texture = texture_features(hand.board[:board_len])

    features = {
        "street": hand.street,
        "position": _seat_position(hand, seat),
        "archetype": archetype,
        "to_call_frac": (legal["call_amount"] / pot_before) if pot_before > 0 else 0.0,
        "n_raises_this_street": _n_raises_this_street(hand),
        **{f"board_{k}": v for k, v in texture.items()},
    }
    if HAD_INITIATIVE_FEATURE:
        features["had_initiative"] = int(_had_preflop_initiative(hand, seat))
    return features


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

    # "monster pot" fix, attempt 3b: PROGRESSIVE_POT_DAMPING (below) can't
    # actually shrink a raise once a raise war is underway, because
    # Hand.min_raise locks in at the size of the last full raise's increment
    # (backend/engine/hand.py) and every subsequent raise is legally bound to
    # be at least that big -- confirmed the reason attempt-3a's dampening had
    # ~no effect (24.4% monster-pot rate, unchanged from baseline): min_raise
    # itself can already be huge by the time this bot acts, so
    # max(raw_amount, hand.min_raise) just floors the damped size back up.
    # Sizing can't fix a raise war already in progress -- only NOT re-raising
    # can. Once the legal min-raise increment is already large relative to
    # the pot, drop "raises" from the allowed set so the model is forced to
    # call or fold instead of compounding the war further.
    if SUPPRESS_RAISE_WHEN_MIN_RAISE_LARGE and allowed.get("raises"):
        pot_before_for_cap = sum(p.total_contributed for p in hand.players.values())
        min_raise_increment_bb = hand.min_raise / hand.big_blind
        pot_bb = pot_before_for_cap / hand.big_blind
        if min_raise_increment_bb > max(RAISE_SUPPRESSION_MIN_INCREMENT_BB, RAISE_SUPPRESSION_POT_FRACTION * pot_bb):
            allowed["raises"] = False

    filtered = {a: p for a, p in proba.items() if allowed.get(a, False) and p > 0}
    if not filtered:
        return ("check" if can_check else "fold"), None

    style = _style_bias(archetype)
    filtered = {a: max(1e-6, p * style.get(a, 1.0)) for a, p in filtered.items()}
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

    # "monster pot" fix, attempt 3 (2026-08-07). Diagnosed with real examples
    # this time (scripts/simulate_abc_bot.py + manual hand-log inspection),
    # not guessed: pulled 662 real monster pots (>50bb) from a batch -- ALL
    # 662 were MULTIWAY (3+ contributors), ZERO were heads-up. The dominant
    # mechanism is a raise WAR among several DIFFERENT players (e.g. a real
    # example: 4 different seats re-raising preflop, $7 -> $32 -> $107),
    # each individual raise a legal, unremarkable fraction of the pot AS IT
    # STOOD when they acted -- no single player repeats, so a per-player
    # history check (first version of this fix, DOWNGRADE_REPEATED_SIZING)
    # can't see it: n_prior_aggressive_actions_this_hand is 0 for every one
    # of those 4 raisers on their FIRST raise. Confirmed this fix (shipped
    # anyway, real but small effect, see docstring above) left the monster-
    # pot rate basically unchanged: ~22-24% baseline -> 21.6-21.7%.
    #
    # This second mechanism, PROGRESSIVE_POT_DAMPING, targets the actual
    # cause: smoothly shrinks the bet-size fraction as the CURRENT pot (in
    # bb, regardless of who contributed it or how) grows past a moderate
    # threshold, applied to every bettor -- so a multiway raise war runs into
    # a shrinking ceiling on EVERY subsequent raise, not just a player's own
    # Nth bet. Starts tightening at a much lower bar (15bb) than the earlier
    # reverted "dampen once already past 50bb" attempt, which was reactive
    # (by the time a pot crosses 50bb it's already the thing being measured)
    # rather than preventive.
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
    return verb, round(amount, 2)


def bot_think_time(action: str) -> float:
    return THINK_TIME_FOLD if action == "fold" else THINK_TIME_OTHER
