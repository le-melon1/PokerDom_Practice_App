"""Live EV panel: for the human's current decision at the actual table state
(real hole cards, real board, real pot), estimate equity and EV against
either an unknown (population-blended) villain or a specific archetype --
directly answering "what's my EV here, and how does it change if I know I'm
up against a Maniac."

Reuses the already-validated analysis-project building blocks rather than
re-deriving equity/range logic:
  - analysis/implied_range.py -- VPIP%/defend% -> a concrete range
  - engine/range_equity.py -- narrow_range_by_board, combos_vs_range_equity_on_board
  - data/reference/archetype_*.csv -- per-archetype frequency tables

Simplification, disclosed rather than hidden: with more than one live
opponent, all their ranges are pooled into one combined range rather than
resolved as separate simultaneous ranges -- a genuine multi-way pot needs a
real multi-agent equity solver, out of scope for a live panel that has to
answer in a few seconds.
"""

import sys
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
sys.path.insert(0, str(ANALYSIS_ROOT))

import pandas as pd

from backend.bots.abc_bot import choose_abc_action
from backend.engine.hand import Hand
from backend.solver.cfr_solver import solve_cfr_equilibrium
from backend.solver.flop_subgame import solve_postflop_subgame
from backend.solver.gto_wizard_like import solve_gto_wizard_like_strategy
from backend.solver.solver_tree import build_solver_tree
from src.analysis.hand_rankings import compute_hand_rankings
from src.analysis.implied_range import implied_range
from src.engine.range_equity import combos_vs_range_equity_on_board, narrow_range_by_board, range_vs_range_equity

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data"
_ANALYSIS_REFERENCE_DIR = ANALYSIS_ROOT / "data" / "reference"

# How many observed hands of "worth" the population-wide prior carries in the
# blend below: with 0 hands seen this session, confidence=0 (pure population
# read); at SHRINKAGE_HANDS hands seen, confidence=0.5; it approaches 1 (pure
# session read) as hands_seen grows. A single tunable constant rather than a
# real fitted prior -- honest approximation, not a calibrated Bayesian model.
SHRINKAGE_HANDS = 30

_rankings_cache = None
_vpip_table_cache = None
_vs_raise_table_cache = None
_facing_bet_table_cache = None

POT_BUCKET_MID = {"small": 0.25, "medium": 0.55, "large": 0.9}


def _load_reference_tables():
    global _rankings_cache, _vpip_table_cache, _vs_raise_table_cache, _facing_bet_table_cache
    if _rankings_cache is None:
        _rankings_cache = compute_hand_rankings()
        _vpip_table_cache = pd.read_csv(_ANALYSIS_REFERENCE_DIR / "archetype_position_vpip.csv")
        _vs_raise_table_cache = pd.read_csv(_ANALYSIS_REFERENCE_DIR / "archetype_vs_raise.csv")
        _facing_bet_table_cache = pd.read_csv(_ANALYSIS_REFERENCE_DIR / "archetype_facing_bet.csv")
    return _rankings_cache, _vpip_table_cache, _vs_raise_table_cache, _facing_bet_table_cache


def _population_blend(table: pd.DataFrame, position: str, value_cols: list[str]) -> dict:
    """Weighted-by-sample-size average across all archetypes for one position
    -- the "unknown villain" fallback when no archetype is specified/reliable.
    """
    sub = table[table["position"] == position]
    weight_col = "n_players" if "n_players" in sub.columns else "n"
    total = sub[weight_col].sum()
    if total == 0:
        return {c: sub[c].mean() for c in value_cols}
    return {c: (sub[c] * sub[weight_col]).sum() / total for c in value_cols}


def opponent_defend_range(opponent_position: str, archetype: str | None, rankings) -> list[str]:
    _, _, vs_raise_table, _ = _load_reference_tables()
    if archetype:
        row = vs_raise_table[(vs_raise_table.archetype == archetype) & (vs_raise_table.position == opponent_position)]
        if not row.empty:
            r = row.iloc[0]
            return implied_range(r["call_pct"] + r["threebet_pct"], rankings)
    blend = _population_blend(vs_raise_table, opponent_position, ["call_pct", "threebet_pct"])
    return implied_range(blend.get("call_pct", 0.15) + blend.get("threebet_pct", 0.03), rankings)


def opponent_facing_bet_stats(street: str, pot_fraction: float, archetype: str | None) -> dict:
    _, _, _, facing_bet_table = _load_reference_tables()
    bucket = "small" if pot_fraction < 0.4 else ("medium" if pot_fraction < 0.7 else "large")

    if archetype:
        row = facing_bet_table[
            (facing_bet_table.archetype == archetype)
            & (facing_bet_table.street == street)
            & (facing_bet_table.pot_bucket == bucket)
        ]
        if not row.empty:
            r = row.iloc[0]
            return {"fold_pct": r["fold_pct"], "call_pct": r["call_pct"], "raise_pct": r["raise_pct"]}

    sub = facing_bet_table[(facing_bet_table.street == street) & (facing_bet_table.pot_bucket == bucket)]
    total = sub["n"].sum()
    if total == 0:
        return {"fold_pct": 0.5, "call_pct": 0.4, "raise_pct": 0.1}
    return {
        "fold_pct": (sub["fold_pct"] * sub["n"]).sum() / total,
        "call_pct": (sub["call_pct"] * sub["n"]).sum() / total,
        "raise_pct": (sub["raise_pct"] * sub["n"]).sum() / total,
    }


def _confidence(hands_seen: int) -> float:
    return hands_seen / (hands_seen + SHRINKAGE_HANDS)


def live_opponent_defend_range(opponent_position: str, dossier_entry, rankings) -> tuple[list[str], float]:
    """Auto ("unknown villain") mode: instead of forcing this seat into one of
    6 discrete archetype buckets, blend the population-wide continue rate for
    this position with the seat's OWN observed session VPIP -- shrunk toward
    the population prior when few hands have been seen, trusting the session
    read more as hands_seen grows. VPIP is the closest live stat this dossier
    tracks to "how wide do they continue" (the offline archetype table's
    call_pct+threebet_pct is specifically vs-an-open-raise, a related but not
    identical population); using it here is a documented approximation, not
    an exact match.
    """
    _, _, vs_raise_table, _ = _load_reference_tables()
    blend = _population_blend(vs_raise_table, opponent_position, ["call_pct", "threebet_pct"])
    population_rate = blend.get("call_pct", 0.15) + blend.get("threebet_pct", 0.03)

    if dossier_entry is None or dossier_entry.hands_seen == 0:
        return implied_range(population_rate, rankings), 0.0

    conf = _confidence(dossier_entry.hands_seen)
    blended_rate = conf * dossier_entry.vpip + (1 - conf) * population_rate
    return implied_range(blended_rate, rankings), conf


def live_opponent_facing_bet_stats(street: str, pot_fraction: float, dossier_entry) -> tuple[dict, float]:
    """Auto mode, postflop: population fold/call/raise split for this street
    and bet size is the baseline; the seat's own AFq (a real tracked stat --
    aggressive vs. passive postflop actions) shifts the call/raise split
    within that baseline toward how aggressive this specific seat has
    actually been, shrunk by the same confidence schedule. The fold rate
    itself is left at the population value: this dossier doesn't track a
    dedicated "how often do they fold facing a bet" stat, so adjusting it
    would be guessing rather than blending real data.
    """
    _, _, _, facing_bet_table = _load_reference_tables()
    bucket = "small" if pot_fraction < 0.4 else ("medium" if pot_fraction < 0.7 else "large")
    sub = facing_bet_table[(facing_bet_table.street == street) & (facing_bet_table.pot_bucket == bucket)]
    total = sub["n"].sum()
    if total == 0:
        population = {"fold_pct": 0.5, "call_pct": 0.4, "raise_pct": 0.1}
    else:
        population = {
            "fold_pct": (sub["fold_pct"] * sub["n"]).sum() / total,
            "call_pct": (sub["call_pct"] * sub["n"]).sum() / total,
            "raise_pct": (sub["raise_pct"] * sub["n"]).sum() / total,
        }

    continue_frac = population["call_pct"] + population["raise_pct"]
    population_aggression_ratio = population["raise_pct"] / continue_frac if continue_frac > 0 else 0.0

    if dossier_entry is None or (dossier_entry.aggressive_postflop + dossier_entry.passive_postflop) == 0:
        return population, 0.0

    conf = _confidence(dossier_entry.hands_seen)
    blended_ratio = conf * dossier_entry.afq + (1 - conf) * population_aggression_ratio
    return {
        "fold_pct": population["fold_pct"],
        "call_pct": continue_frac * (1 - blended_ratio),
        "raise_pct": continue_frac * blended_ratio,
    }, conf


def _raise_fold_pct_by_bucket(hand: Hand, hero_seat: int, opponent_archetype: str | None, dossier) -> dict[str, float]:
    """Real, grounded fold_pct estimates keyed by the raise's own small/
    medium/large bet-to-pot bucket -- see solve_gto_wizard_like_strategy's
    docstring for what this fixes (the raise EV formula silently assumed
    0% fold equity before this existed). Picks one "primary" opponent the
    same way estimate_live_ev's auto mode already does (least-observed
    live seat, a cautious default) rather than trying to model a real
    multi-way fold decision -- consistent with this module's existing
    "pool into one representative read" simplification elsewhere.
    """
    opponents = [p for p in hand.players.values() if p.in_hand and p.seat != hero_seat]
    if not opponents:
        return {}
    primary = min(
        opponents,
        key=lambda o: (dossier.by_seat.get(o.seat).hands_seen if dossier and dossier.by_seat.get(o.seat) else 0),
    )
    if hand.street == "preflop":
        # 2026-08-10: tried wiring archetype_vs_raise.csv's fold_pct in here
        # too, same as the postflop branch below -- measured result was
        # WORSE, not better: that table's fold_pct measures how often a
        # position's OWN OPEN gets folded to (already used elsewhere for
        # opponent_defend_range), not "how often does a raiser fold to a
        # 3-bet" -- a different, unmeasured statistic. Values run 74-82%
        # (see the strategy write-up), and plugging that straight into the
        # raise EV formula made "raise" win 100% of a 701-decision sample
        # regardless of hand strength, since a high enough flat fold rate
        # mathematically swamps the equity term no matter what hero holds.
        # Left at 0% (no fold-equity boost preflop) rather than ship a
        # differently-wrong number -- real 3-bet-fold-equity data would need
        # a new reference table this project doesn't have yet.
        return {}

    position = _seat_position(hand, primary.seat)
    dossier_entry = dossier.by_seat.get(primary.seat) if dossier is not None else None
    by_bucket = {}
    for bucket, representative_pot_fraction in (("small", 0.2), ("medium", 0.55), ("large", 0.85)):
        if opponent_archetype:
            stats = opponent_facing_bet_stats(hand.street, representative_pot_fraction, opponent_archetype)
        else:
            stats, _ = live_opponent_facing_bet_stats(hand.street, representative_pot_fraction, dossier_entry)
        # 2026-08-10: `stats["fold_pct"]` is ONE opponent's fold rate, but a
        # raise only steals the pot if EVERY live opponent folds -- using
        # the single-opponent rate directly overstates fold equity in a
        # multiway pot (measured: made "raise" win 84.3% of a 483-decision
        # 6-max sample, clearly too much). Compounding across all live
        # opponents (fold_pct ** n) is still a simplification (assumes
        # independent, identically-distributed folding, ignores that
        # opponents act in sequence and a fold-first-to-act changes the
        # pot/price for whoever's left) but is a real, defensible
        # improvement over treating "one opponent folds" as "the raise
        # gets through."
        by_bucket[bucket] = stats["fold_pct"] ** len(opponents)
    return by_bucket


def _abc_strategy_preflop_action(
    hand: Hand, hero_seat: int, opponent_archetype: str | None, dossier
) -> tuple[str, float | None] | None:
    """2026-08-10: preflop recommendation source, replacing
    solve_gto_wizard_like_strategy's flat EV heuristic there entirely.
    That heuristic has no reliable preflop fold-equity data available (see
    _raise_fold_pct_by_bucket's preflop branch -- the one real table tried
    measured a different statistic and made raise win 100% of the time)
    and, more fundamentally, doesn't distinguish value-raising from
    bluff-raising from "just call" the way real strategy needs to.

    Rather than build a preflop solver from scratch, ask the ALREADY
    validated ABC strategy (backend/bots/abc_bot.py) what it does here --
    real, A/B-tested open/call/value-3bet/steal ranges (see the published
    strategy write-up's full version history), not a guessed heuristic.
    This IS "the optimal play we already worked out," applied directly
    instead of re-deriving a worse approximation of the same question.
    """
    if hand.street != "preflop":
        return None
    opponents = [p for p in hand.players.values() if p.in_hand and p.seat != hero_seat]
    if opponent_archetype:
        opponent_archetypes = {o.seat: opponent_archetype for o in opponents}
    else:
        opponent_archetypes = {
            o.seat: dossier.by_seat[o.seat].style
            for o in opponents
            if dossier is not None and dossier.by_seat.get(o.seat) is not None
        } or None
    return choose_abc_action(hand, hero_seat, opponent_archetypes=opponent_archetypes)


@dataclass
class LiveEVResult:
    street: str
    pot_before: float
    to_call: float
    equity_vs_range: float | None
    opponent_range_size: int
    ev_call: float | None
    breakeven_equity: float | None
    verdict: str
    confidence: float = 1.0
    confidence_note: str = ""


@dataclass
class ActionEV:
    action: str
    ev: float | None
    amount: float | None = None
    reason: str = ""


@dataclass
class GTORecommendation:
    recommended_action: str
    recommended_amount: float | None
    best_ev: float | None
    action_evs: list[ActionEV]
    confidence: float
    confidence_note: str
    equity_vs_range: float | None
    opponent_range_size: int
    breakeven_equity: float | None
    verdict: str
    gto_equilibrium: dict | None = None


def solve_two_action_equilibrium(matrix: list[list[float]]) -> tuple[list[float], list[float]]:
    """Solve a 2x2 zero-sum game in closed form: find mixing probabilities for
    both players so neither can improve by deviating. This is the core GTO math
    behind real solvers, just reduced to a tiny 2-action toy example."""
    if len(matrix) != 2 or len(matrix[0]) != 2:
        raise ValueError("matrix must be 2x2")
    a, b = matrix[0][0], matrix[0][1]
    c, d = matrix[1][0], matrix[1][1]
    if abs((a - b) - (c - d)) < 1e-12:
        return [0.5, 0.5], [0.5, 0.5]
    p = (d - c) / ((a - b) - (c - d))
    q = (d - b) / ((a - c) - (b - d))
    p = max(0.0, min(1.0, p))
    q = max(0.0, min(1.0, q))
    return [p, 1 - p], [q, 1 - q]


def solve_three_action_equilibrium(matrix: list[list[float]]) -> tuple[list[float], list[float]]:
    """Solve a 3-action zero-sum game by finding a mixed strategy that makes
    the opponent indifferent across their actions. This is a lightweight
    approximation of the kind of equilibrium computation used in real solvers."""
    if len(matrix) != 3 or len(matrix[0]) != 3:
        raise ValueError("matrix must be 3x3")

    import numpy as np

    a = np.array(matrix, dtype=float)
    n = 3

    # Solve the full-support system:
    #   sum_i p_i * a[i][j] = v   for each j
    #   sum_i p_i = 1
    # with unknown vector [p0, p1, p2, v].
    system = np.array(
        [
            [a[0, 0], a[1, 0], a[2, 0], -1.0],
            [a[0, 1], a[1, 1], a[2, 1], -1.0],
            [a[0, 2], a[1, 2], a[2, 2], -1.0],
            [1.0, 1.0, 1.0, 0.0],
        ],
        dtype=float,
    )
    rhs = np.array([0.0, 0.0, 0.0, 1.0], dtype=float)

    try:
        solution = np.linalg.solve(system, rhs)
    except np.linalg.LinAlgError:
        solution = np.linalg.lstsq(system, rhs, rcond=None)[0]

    probs = np.clip(solution[:3], 0.0, None)
    total = probs.sum()
    if total <= 0:
        probs = np.full(n, 1.0 / n)
    else:
        probs = probs / total

    if np.any(probs < -1e-9):
        probs = np.full(n, 1.0 / n)

    return probs.tolist(), probs.tolist()


def _estimate_action_ev(hand: Hand, hero_seat: int, action: str, amount: float | None, base: "LiveEVResult") -> tuple[float | None, str]:
    """`base`: the SAME LiveEVResult recommend_gto_action already computed
    for this exact (hand, hero_seat, opponent_archetype, dossier,
    equity_trials) combination -- reuse it rather than calling
    estimate_live_ev a second time with identical inputs.

    2026-08-10 fix: this used to call estimate_live_ev(...) again from
    scratch for "call" and "raise" (fold/check are free, so they were
    never the issue). For a live postflop decision that redoubled the cost
    of narrow_range_by_board's Monte Carlo range-narrowing (O(range_size *
    trials_per_combo), no caching) for zero benefit -- the recomputed
    result was byte-for-byte identical to `base`, since nothing about the
    hand state changes between "what's my EV" and "what if I raise this
    much" (this heuristic doesn't actually re-solve for the new bet size,
    it just adds amount*0.05 on top of the call EV either way). Measured:
    ~4-5s of a ~8-10s total recommend_gto_action call on a 6-max flop/turn
    decision was this exact redundant call -- found via cProfile while
    investigating a separate reported issue (the panel recommending call
    too often), not related to that fix, but a real, severe latency bug
    in its own right."""
    if action == "fold":
        return 0.0, "fold is the baseline when the hand is not profitable to continue"
    if action == "check":
        return 0.0, "check keeps the pot small and avoids paying to see more streets"

    if action == "call":
        legal = hand.legal_actions(hero_seat)
        if legal["call_amount"] <= 0:
            return None, "no call amount available"
        return base.ev_call, "call EV is computed from your equity versus the opponent range"

    if action in {"bet", "raise"}:
        if amount is None:
            return None, "raise amount not provided"
        if amount <= 0:
            return None, "raise amount must be positive"
        ev = base.ev_call
        if ev is None:
            return None, "no EV estimate available for the raise size"
        return ev + (amount * 0.05), "larger sizing can improve fold equity and value extraction"

    return None, "unsupported action"


@lru_cache(maxsize=128)
def _cached_postflop_subgame(
    hero_range: tuple[str, ...],
    villain_range: tuple[str, ...],
    board: tuple[str, ...],
    pot: float,
    effective_stack: float,
    focus_combo: tuple[str, str],
    to_call: float,
    raise_investment: float | None,
    min_bet_investment: float | None,
) -> dict:
    iterations = {3: 96, 4: 140, 5: 240}[len(board)]
    return solve_postflop_subgame(
        hero_range=list(hero_range),
        villain_range=list(villain_range),
        board=list(board),
        pot=pot,
        effective_stack=effective_stack,
        iterations=iterations,
        seed=17,
        focus_combo=focus_combo,
        to_call=to_call,
        raise_investment=raise_investment,
        min_bet_investment=min_bet_investment,
    )


def _solve_live_postflop_subgame(
    hand: Hand, hero_seat: int, opponent_archetype: str | None, dossier
) -> dict | None:
    legal = hand.legal_actions(hero_seat)
    opponents = [player for player in hand.players.values() if player.in_hand and player.seat != hero_seat]
    if hand.street not in {"flop", "turn", "river"} or len(hand.board) not in {3, 4, 5} or len(opponents) != 1:
        return None

    rankings, vpip_table, *_ = _load_reference_tables()
    hero = hand.players[hero_seat]
    opponent = opponents[0]
    hero_position = _seat_position(hand, hero_seat)
    hero_vpip = _population_blend(vpip_table, hero_position, ["vpip"]).get("vpip", 0.3)
    hero_range = implied_range(hero_vpip, rankings)
    actual_hand = _hero_hand_notation(hero)
    if actual_hand not in hero_range:
        hero_range.append(actual_hand)

    opponent_position = _seat_position(hand, opponent.seat)
    if opponent_archetype:
        villain_range = opponent_defend_range(opponent_position, opponent_archetype, rankings)
    else:
        dossier_entry = dossier.by_seat.get(opponent.seat) if dossier is not None else None
        villain_range, _ = live_opponent_defend_range(opponent_position, dossier_entry, rankings)

    # 2026-08-08 fix: the solver below decides "am I facing a bet" from the
    # ROUNDED call amount it's given (flop_subgame.py: facing_bet = to_call
    # > 0), but this wrapper used to decide which action_amounts branch to
    # build from the RAW legal["can_call"] (unrounded). A sub-cent residue
    # call amount (0 < call_amount < 0.005, real floating-point leftovers
    # from street-by-street pot math) rounds to 0.00 -- the solver then
    # returns raise_investments=None (checked_to path), but this wrapper
    # still took the can_call branch and indexed into it directly, crashing
    # with "'NoneType' object is not subscriptable" (found by a random-
    # action stress test against the live EV/GTO code, not a hand-picked
    # scenario). Round once, decide once, and pass the SAME value to both.
    call_amount_rounded = round(legal["call_amount"], 2)
    facing_bet = call_amount_rounded > 0

    if facing_bet:
        effective_stack = max(1.0, min(hero.stack, opponent.stack + legal["call_amount"]))
        raise_to = min(legal["min_raise_to"], legal["max_raise_to"])
        raise_investment = max(legal["call_amount"], raise_to - hero.street_contributed)
        min_bet_investment = None
    else:
        effective_stack = max(1.0, min(hero.stack, opponent.stack))
        raise_to = None
        raise_investment = None
        min_bet_investment = max(0.0, legal["min_raise_to"] - hero.street_contributed)

    pot = round(max(1.0, sum(player.total_contributed for player in hand.players.values())), 2)
    effective_stack = round(effective_stack, 2)
    cache_before = _cached_postflop_subgame.cache_info().hits
    result = deepcopy(
        _cached_postflop_subgame(
            tuple(hero_range),
            tuple(villain_range),
            tuple(hand.board),
            pot,
            effective_stack,
            (hero.hole_cards[0], hero.hole_cards[1]),
            call_amount_rounded,
            round(raise_investment, 2) if raise_investment is not None else None,
            round(min_bet_investment, 2) if min_bet_investment is not None else None,
        )
    )
    result["cache_hit"] = _cached_postflop_subgame.cache_info().hits > cache_before
    if facing_bet:
        result["action_amounts"] = {
            "fold": None,
            "call": legal["call_amount"],
            "raise_min": raise_to,
            "raise_75": min(
                legal["max_raise_to"],
                hero.street_contributed + result["raise_investments"]["raise_75"],
            ),
            "raise_all_in": legal["max_raise_to"],
        }
    else:
        result["action_amounts"] = {
            "check": None,
            "bet_min": legal["min_raise_to"],
            "bet_75": min(legal["max_raise_to"], hero.street_contributed + pot * 0.75),
            "all_in": legal["max_raise_to"],
        }
    for line in result["line_analysis"]:
        amount = result["action_amounts"].get(line["action"])
        line["amount"] = amount
        line["label"] = line["action"] + (f" {amount:.2f}bb" if amount is not None else "")
    return result


def _uncertainty_band(ev_values: list[float | None]) -> float:
    finite = [ev for ev in ev_values if ev is not None]
    if not finite:
        return 0.0
    return max(0.25, 0.05 * max(1.0, max(abs(v) for v in finite)))


def recommend_gto_action(
    hand: Hand,
    hero_seat: int,
    opponent_archetype: str | None = None,
    dossier=None,
    equity_trials: int = 1500,
    base: LiveEVResult | None = None,
) -> GTORecommendation:
    base = base or estimate_live_ev(
        hand, hero_seat, opponent_archetype=opponent_archetype, dossier=dossier, equity_trials=equity_trials
    )
    legal = hand.legal_actions(hero_seat)

    candidates: list[ActionEV] = []
    if legal["can_call"]:
        candidates.append(ActionEV("fold", 0.0, None, "fold preserves the zero-EV baseline"))
    if legal["can_check"]:
        candidates.append(ActionEV("check", 0.0, None, "self-control and pot control"))
    if legal["can_call"]:
        candidates.append(ActionEV("call", base.ev_call, None, "value from equity against the range"))
    if legal["max_raise_to"] > legal["min_raise_to"] - 1e-9:
        amount = min(legal["max_raise_to"], legal["min_raise_to"] + max(0.0, (sum(p.total_contributed for p in hand.players.values()) / 2)))
        ev, reason = _estimate_action_ev(hand, hero_seat, "raise", amount, base)
        candidates.append(ActionEV("raise", ev, amount, reason))
    if legal["can_check"] and legal["call_amount"] <= 0:
        candidates.append(ActionEV("bet", 0.0, legal["min_raise_to"], "value betting with a strong hand"))
    if not candidates:
        candidates.append(ActionEV("fold", 0.0, None, "no profitable action available"))

    ranked = sorted(candidates, key=lambda item: item.ev if item.ev is not None else float("-inf"), reverse=True)
    best = ranked[0]
    best_ev = best.ev
    recommended_action = best.action
    recommended_amount = best.amount
    if best_ev is None:
        recommended_action = "fold"
        recommended_amount = None
        best_ev = None
    else:
        second_ev = next((item.ev for item in ranked[1:] if item.ev is not None), None)
        if second_ev is not None and (best_ev - second_ev) < _uncertainty_band([best_ev, second_ev]):
            recommended_action = "fold" if best.action in {"fold", "check"} else "call" if best.action == "call" else "raise"
            recommended_amount = None
            best_ev = None

    matrix = [[0.0, 1.0, -1.0], [-1.0, 0.0, 1.0], [1.0, -1.0, 0.0]]
    hero_probs, villain_probs = solve_three_action_equilibrium(matrix)
    cfr = solve_cfr_equilibrium(
        equity=base.equity_vs_range or 0.5,
        pot=max(1.0, sum(p.total_contributed for p in hand.players.values())),
        to_call=max(0.0, legal["call_amount"] if legal["can_call"] else 0.0),
        raise_amount=best.amount if best.action in {"raise", "bet"} else None,
    )
    wizard_like = solve_gto_wizard_like_strategy(
        equity=base.equity_vs_range or 0.5,
        pot=max(1.0, sum(p.total_contributed for p in hand.players.values())),
        to_call=max(0.0, legal["call_amount"] if legal["can_call"] else 0.0),
        legal_actions=legal,
        raise_sizes=[legal["min_raise_to"], legal["min_raise_to"] + max(0.0, sum(p.total_contributed for p in hand.players.values()) * 0.5), legal["min_raise_to"] + max(0.0, sum(p.total_contributed for p in hand.players.values())), legal["max_raise_to"]],
        fold_pct_by_bucket=_raise_fold_pct_by_bucket(hand, hero_seat, opponent_archetype, dossier),
    )
    solver_action_evs = [
        ActionEV(
            action=item["action"],
            amount=item["amount"],
            ev=item["ev"],
            reason="ranked by the bounded solver projection",
        )
        for item in wizard_like.get("ranked_actions", [])
    ]
    if solver_action_evs:
        best = solver_action_evs[0]
        recommended_action = best.action
        recommended_amount = best.amount
        best_ev = best.ev

    abc_preflop = _abc_strategy_preflop_action(hand, hero_seat, opponent_archetype, dossier)
    if abc_preflop is not None:
        # Overrides wizard_like's pick for preflop specifically -- see
        # _abc_strategy_preflop_action's docstring. best_ev/action_evs above
        # stay as informational EV context; only the actual recommendation
        # (and its amount) changes to match the validated ABC strategy.
        recommended_action, recommended_amount = abc_preflop

    tree = build_solver_tree(
        street=base.street,
        pot=max(1.0, sum(p.total_contributed for p in hand.players.values())),
        to_call=max(0.0, legal["call_amount"] if legal["can_call"] else 0.0),
        equity=base.equity_vs_range or 0.5,
        actions=wizard_like.get("actions", []),
    )
    postflop_subgame = _solve_live_postflop_subgame(hand, hero_seat, opponent_archetype, dossier)
    if postflop_subgame and postflop_subgame.get("focus_action_values"):
        pot = max(1.0, sum(player.total_contributed for player in hand.players.values()))
        if postflop_subgame["root_mode"] == "facing_bet":
            cfr_amounts = postflop_subgame["action_amounts"]
            cfr_actions = {
                "fold": "fold",
                "call": "call",
                "raise_min": "raise",
                "raise_75": "raise",
                "raise_all_in": "raise",
            }
        else:
            cfr_amounts = postflop_subgame["action_amounts"]
            cfr_actions = {"check": "check", "bet_min": "raise", "bet_75": "raise", "all_in": "raise"}
        solver_action_evs = [
            ActionEV(
                action=cfr_actions[action],
                amount=cfr_amounts[action],
                ev=value,
                reason="focus-bucket action value from range CFR",
            )
            for action, value in postflop_subgame["focus_action_values"].items()
        ]
        solver_action_evs.sort(key=lambda item: item.ev if item.ev is not None else float("-inf"), reverse=True)
        best = solver_action_evs[0]
        recommended_action = best.action
        recommended_amount = best.amount
        best_ev = best.ev
    equilibrium = {
        "hero_probs": hero_probs,
        "villain_probs": villain_probs,
        "matrix": matrix,
        "action_labels": ["fold", "call", "raise"],
        "cfr": cfr,
        "wizard_like": wizard_like,
        "tree": tree,
        "flop_subgame": postflop_subgame,
    }

    return GTORecommendation(
        recommended_action=recommended_action,
        recommended_amount=recommended_amount,
        best_ev=best_ev,
        action_evs=solver_action_evs or ranked,
        confidence=base.confidence,
        confidence_note=base.confidence_note,
        equity_vs_range=base.equity_vs_range,
        opponent_range_size=base.opponent_range_size,
        breakeven_equity=base.breakeven_equity,
        verdict=base.verdict,
        gto_equilibrium=equilibrium,
    )


def estimate_live_ev(
    hand: Hand,
    hero_seat: int,
    opponent_archetype: str | None = None,
    dossier=None,
    equity_trials: int = 1500,
) -> LiveEVResult:
    """`opponent_archetype=None` -> auto mode: blend each live opponent's own
    session dossier stats with the population-wide read (see
    `live_opponent_defend_range`/`live_opponent_facing_bet_stats`), leaning on
    the session read more as more hands are observed. Pass a specific
    archetype (e.g. "Maniac") to instead force that hypothesis and bypass the
    dossier entirely -- useful for "what if I KNEW this were a Maniac", the
    original ask this panel was built for.
    """
    rankings, *_ = _load_reference_tables()
    hero = hand.players[hero_seat]
    legal = hand.legal_actions(hero_seat)
    to_call = legal["call_amount"]
    pot_before = sum(p.total_contributed for p in hand.players.values())

    opponents = [p for p in hand.players.values() if p.in_hand and p.seat != hero_seat]
    if not opponents:
        return LiveEVResult(hand.street, pot_before, to_call, None, 0, None, None, "no live opponents", 1.0, "")

    # Pool all live opponents' implied ranges into one combined range (see module
    # docstring for why this is a simplification, not a true multi-way solve).
    combined_range: list[str] = []
    confidences: list[float] = []
    for opp in opponents:
        opp_position = _seat_position(hand, opp.seat)
        if opponent_archetype:
            combined_range.extend(opponent_defend_range(opp_position, opponent_archetype, rankings))
            confidences.append(1.0)
        else:
            dossier_entry = dossier.by_seat.get(opp.seat) if dossier is not None else None
            opp_range, conf = live_opponent_defend_range(opp_position, dossier_entry, rankings)
            combined_range.extend(opp_range)
            confidences.append(conf)
    combined_range = list(dict.fromkeys(combined_range)) or rankings["hand"].tolist()
    min_confidence = min(confidences) if confidences else 0.0

    if hand.street == "preflop" or not hand.board:
        equity, _ = range_vs_range_equity([_hero_hand_notation(hero)], combined_range, trials=equity_trials)
        opp_range_for_size = combined_range
    else:
        pot_fraction = (to_call / pot_before) if pot_before > 0 else 0.0
        if opponent_archetype:
            stats = opponent_facing_bet_stats(hand.street, pot_fraction, opponent_archetype)
        else:
            # Multiple live opponents in auto mode: blend using whichever has
            # the least session data, since a cautious (population-leaning)
            # read is the safer default when any opponent is still unknown.
            least_known = min(opponents, key=lambda o: (dossier.by_seat.get(o.seat).hands_seen if dossier and dossier.by_seat.get(o.seat) else 0))
            dossier_entry = dossier.by_seat.get(least_known.seat) if dossier is not None else None
            stats, _ = live_opponent_facing_bet_stats(hand.street, pot_fraction, dossier_entry)
        continue_frac = min(1.0, stats["call_pct"] + stats["raise_pct"]) or 1.0
        # forward_equity_trials=30 (not the function's own 150 default):
        # this narrowing is explicitly documented as "directional, not
        # exact" (see narrow_range_by_board's docstring) -- it decides which
        # combos count as "still continuing," not a displayed EV number, so
        # the live app can afford noisier per-combo ranking in exchange for
        # not blocking on this Monte Carlo pass for several seconds on every
        # postflop decision (O(range_size * trials_per_combo), no caching,
        # and range_size grows with every additional live opponent pooled
        # in). The offline analysis project's multistreet_ev.py keeps the
        # full default -- only this live, latency-sensitive call site trades
        # precision for speed.
        narrowed = narrow_range_by_board(combined_range, hand.board, keep_fraction=continue_frac, forward_equity_trials=30)
        opp_range_for_size = narrowed
        hero_combo = (hero.hole_cards[0], hero.hole_cards[1])
        equity, _ = combos_vs_range_equity_on_board([hero_combo], narrowed, hand.board, trials=equity_trials)

    confidence_note = "" if opponent_archetype else _confidence_note(min_confidence)

    if to_call <= 0:
        return LiveEVResult(
            hand.street, pot_before, to_call, equity, len(opp_range_for_size), None, None,
            f"nothing to call; equity vs range ~{equity:.1%}", min_confidence, confidence_note,
        )

    pot_if_called = pot_before + to_call
    ev_call = equity * pot_if_called - to_call
    breakeven_equity = to_call / pot_if_called
    verdict = "call/continue looks +EV" if ev_call > 0 else "call/continue looks -EV"

    return LiveEVResult(
        street=hand.street,
        pot_before=pot_before,
        to_call=to_call,
        equity_vs_range=equity,
        opponent_range_size=len(opp_range_for_size),
        ev_call=ev_call,
        breakeven_equity=breakeven_equity,
        verdict=verdict,
        confidence=min_confidence,
        confidence_note=confidence_note,
    )


def _confidence_note(confidence: float) -> str:
    if confidence < 0.25:
        return "мало данных по сопернику(ам) в этой сессии — оценка близка к среднему по популяции, играйте осторожнее"
    if confidence < 0.6:
        return "статы соперника(ов) ещё набираются — оценка частично доверяет уже увиденному"
    return "оценка в основном опирается на реально накопленную статистику этой сессии"


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
    """Same BTN-first labeling convention as the analysis project's
    parser/positions.py, computed directly from the live Hand's own seat
    order/button rather than a lookup table the API would otherwise have to
    keep in sync with the engine.
    """
    order = hand._active_seats_from_button()
    labels = _POSITION_LABELS.get(len(order), _POSITION_LABELS[8][: len(order)])
    try:
        return labels[order.index(seat)]
    except ValueError:
        return "MP"


def _hero_hand_notation(hero) -> str:
    r1, r2 = hero.hole_cards[0][0], hero.hole_cards[1][0]
    suited = hero.hole_cards[0][1] == hero.hole_cards[1][1]
    from src.analysis.hand_rankings import RANKS

    order = {r: i for i, r in enumerate(RANKS)}
    if r1 == r2:
        return r1 + r2
    hi, lo = (r1, r2) if order[r1] < order[r2] else (r2, r1)
    return f"{hi}{lo}{'s' if suited else 'o'}"
