#!/usr/bin/env python3
"""Chance-node enumeration after the first baseline/treatment split.

Default methodology for this script:
- run baseline and treatment in lockstep on the same hand;
- when hero's action first differs, average the continuation over every
  possible next board card;
- count that whole averaged branch as ONE observation, not as 30-45 hands.

Known caveats / failure modes:
- This script is still a per-hand EV probe, not the full session simulator:
  each hand starts from fresh 200bb stacks, so it intentionally removes
  cross-hand bankroll/turnover feedback.
- It enumerates only the NEXT board card, not the full turn+river tree. If
  most noise is from later betting decisions or the full runout, CI can remain
  wide.
- It only enumerates after the first HERO action split. Non-hero stochastic
  divergence is controlled with common-random seeds, not fully branched.
- Branches must never be counted as independent samples. One divergent hand
  contributes one averaged delta; otherwise CI is falsely overconfident.
- Very rare flags still need enough independent divergent hands. Enumerating
  40 cards for two spots does not prove the population effect.
- This is CPU-expensive when splits are frequent. Always compare CI shrink
  against slowdown before using it for a large batch.
"""

import copy
import math
import statistics
import sys
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(__file__).rsplit("/scripts/", 1)[0])

import backend.bots.abc_bot as abc_bot
from backend.bots.abc_bot import choose_abc_action
from backend.bots.behavior_clone import choose_bot_action
from backend.engine.cards_import import Card
from backend.engine.hand import IllegalAction
from backend.engine.table import Table
from backend.sessions.live_dynamics import ARCHETYPE_POOL, TableTurnover
from scripts.simulate_abc_bot import (
    BOT_ACTION_SEED_STREAM,
    DECK_SEED_STREAM,
    HERO_SEAT,
    MAX_SEATS,
    PRESET_FLAG_GROUPS,
    RAKE_CAP_BB,
    RAKE_PERCENT,
    STARTING_STACK,
    _NON_BOOLEAN_FLAG_OFF_VALUES,
    _NON_BOOLEAN_FLAG_ON_VALUES,
    _common_seed,
    _sync_value_3bet,
)

EXTRA_TEST_GROUPS = {
    "v3-calling-raises": (["ALLOW_CALLING_RAISES"], "v3 allow calling raises"),
    "v6-unconditional-cbet": (["UNCONDITIONAL_FLOP_CBET"], "v6 unconditional flop cbet"),
    "v10-opponent-aware": (["OPPONENT_AWARE_ARCHETYPES"], "v10 opponent-aware loose calls"),
    "v11-multiway-aware": (
        ["MULTIWAY_NARROW_CALL_RANGE", "MULTIWAY_DISABLE_AIR_CBET", "MULTIWAY_DISABLE_LOOSE_CALL"],
        "v11 multiway aware",
    ),
    "v14-steal-wide": (["STEAL_WIDER_VS_NIT"], "v14 steal wider vs nit"),
    "v14-size-target": (["SIZING_TARGET_ARCHETYPES"], "v14 value size target archetypes"),
    "v15-loose-3bet": (["WIDER_3BET_VS_LOOSE"], "v15 wider 3bet vs loose"),
    "v15-turn-size": (["SIZE_UP_ON_TURN"], "v15 size up on turn"),
    "v19-hero-pot-damping": (["HERO_PROGRESSIVE_POT_DAMPING"], "v19 hero pot damping"),
    "v21-squeeze-wide": (["SQUEEZE_WIDER_RANGE"], "v21 squeeze wider range"),
    "v21-squeeze-size": (["SQUEEZE_SIZE_UP_PER_CALLER"], "v21 squeeze size up per caller"),
    "v21-squeeze-both": (["SQUEEZE_WIDER_RANGE", "SQUEEZE_SIZE_UP_PER_CALLER"], "v21 squeeze wider+size"),
    "v22-value-raise": (["VALUE_RAISE_FACING_BET"], "v22 value raise two-pair+"),
    "v22-value-raise-trips": (
        ["VALUE_RAISE_FACING_BET", "VALUE_RAISE_TRIPS_OR_BETTER_ONLY"],
        "v22 value raise trips+ only",
    ),
    "v23-overbet-fold": (["FOLD_TOP_PAIR_VS_OVERBET"], "v23 fold top pair vs overbet"),
    "v23-size-strong": (["SIZE_UP_WITH_VERY_STRONG_HAND"], "v23 size up strong hand"),
    "v23-size-wet": (["SIZE_UP_ON_WET_BOARD"], "v23 size up wet board"),
    "v23-size-both": (["SIZE_UP_WITH_VERY_STRONG_HAND", "SIZE_UP_ON_WET_BOARD"], "v23 size up strong+wet"),
    "v24-bluff-3bet": (["BLUFF_3BET_VS_TIGHT"], "v24 bluff 3bet vs tight"),
}

RULE_TEST_GROUPS = {
    "r01-calling-raises": (["ALLOW_CALLING_RAISES"], "r01 calling raises"),
    "r02-unconditional-cbet": (["UNCONDITIONAL_FLOP_CBET"], "r02 unconditional flop cbet"),
    "r03-opponent-aware-loose-call": (["OPPONENT_AWARE_ARCHETYPES"], "r03 opponent-aware loose calls"),
    "r04-wide-value-3bet": (["USE_WIDE_VALUE_3BET"], "r04 wide value 3bet"),
    "r05-steal-wide-vs-nit": (["STEAL_WIDER_VS_NIT"], "r05 steal wider vs nit"),
    "r06-size-up-vs-nit-tag": (["SIZING_TARGET_ARCHETYPES"], "r06 value size target archetypes"),
    "r07-wider-3bet-vs-loose": (["WIDER_3BET_VS_LOOSE"], "r07 wider 3bet vs loose"),
    "r08-size-up-turn": (["SIZE_UP_ON_TURN"], "r08 size up on turn"),
    "r09-iso-raise-limpers": (["ISO_RAISE_OVER_LIMPERS"], "r09 iso-raise over limpers"),
    "r10-donk-bluff-vs-tight": (["DONK_BLUFF_VS_TIGHT"], "r10 donk bluff vs tight"),
    "r11-hero-pot-damping": (["HERO_PROGRESSIVE_POT_DAMPING"], "r11 hero progressive pot damping"),
    "r12-tight-big-iso-limpers": (["TIGHT_BIG_ISO_RAISE_LIMPERS"], "r12 tight big iso-raise limpers"),
}


def _all_test_groups() -> dict[str, tuple[list[str], str]]:
    return {**PRESET_FLAG_GROUPS, **EXTRA_TEST_GROUPS, **RULE_TEST_GROUPS}


PSEUDO_OPPONENT_AWARE = "OPPONENT_AWARE_ARCHETYPES"
PSEUDO_FLAGS = {PSEUDO_OPPONENT_AWARE}
MULTIWAY_SUBFLAGS = {"MULTIWAY_NARROW_CALL_RANGE", "MULTIWAY_DISABLE_AIR_CBET", "MULTIWAY_DISABLE_LOOSE_CALL"}

ALL_COMPARISON_FLAGS = [
    "ALLOW_CALLING_RAISES",
    "UNCONDITIONAL_FLOP_CBET",
    "USE_WIDE_VALUE_3BET",
    "STEAL_WIDER_VS_NIT",
    "SIZING_TARGET_ARCHETYPES",
    "WIDER_3BET_VS_LOOSE",
    "SIZE_UP_ON_TURN",
    "ISO_RAISE_OVER_LIMPERS",
    "TIGHT_BIG_ISO_RAISE_LIMPERS",
    "DONK_BLUFF_VS_TIGHT",
    "HERO_PROGRESSIVE_POT_DAMPING",
    "SQUEEZE_WIDER_RANGE",
    "SQUEEZE_SIZE_UP_PER_CALLER",
    "VALUE_RAISE_FACING_BET",
    "VALUE_RAISE_TRIPS_OR_BETTER_ONLY",
    "FOLD_TOP_PAIR_VS_OVERBET",
    "SIZE_UP_WITH_VERY_STRONG_HAND",
    "SIZE_UP_ON_WET_BOARD",
    "BLUFF_3BET_VS_TIGHT",
    "BARREL_BLUFF_VS_TIGHT",
    "FOLD_PREMIUM_VS_EXTREME_AGGRO",
    "RIVER_OVERBET_NUTS_VS_LOOSE",
    "OPTIMAL_VALUE_SIZING_PER_ARCHETYPE",
    "ISO_WIDER_RANGE_OVER_LIMPERS",
    "SIZE_SCALED_CALL_RANGE",
    *sorted(MULTIWAY_SUBFLAGS),
]

HISTORICAL_PRIOR_ON_FLAGS = {
    "v11-multiway-aware": ["USE_WIDE_VALUE_3BET"],
    "v14-steal-sizing": ["USE_WIDE_VALUE_3BET"],
    "v15-loose-3bet-turn": ["USE_WIDE_VALUE_3BET", "STEAL_WIDER_VS_NIT", "SIZING_TARGET_ARCHETYPES"],
    "v16-iso-limpers": [
        "USE_WIDE_VALUE_3BET",
        "STEAL_WIDER_VS_NIT",
        "SIZING_TARGET_ARCHETYPES",
        "WIDER_3BET_VS_LOOSE",
        "SIZE_UP_ON_TURN",
    ],
    "v17-donk-bluff": [
        "USE_WIDE_VALUE_3BET",
        "STEAL_WIDER_VS_NIT",
        "SIZING_TARGET_ARCHETYPES",
        "WIDER_3BET_VS_LOOSE",
        "SIZE_UP_ON_TURN",
        "ISO_RAISE_OVER_LIMPERS",
    ],
    # v21+ happened after the monster-pot damping work. Squeeze itself stays
    # off in later historical baselines: the changelog says it was not
    # confirmed and shipped off, even if today's module default drifts.
    "v21-squeeze-wide": [
        "USE_WIDE_VALUE_3BET",
        "STEAL_WIDER_VS_NIT",
        "SIZING_TARGET_ARCHETYPES",
        "WIDER_3BET_VS_LOOSE",
        "SIZE_UP_ON_TURN",
        "ISO_RAISE_OVER_LIMPERS",
        "DONK_BLUFF_VS_TIGHT",
        "HERO_PROGRESSIVE_POT_DAMPING",
    ],
}
HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-size"] = HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-wide"]
HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-both"] = HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-wide"]

for _preset in (
    "v22-value-raise",
    "v22-value-raise-trips",
    "v23-overbet-fold",
    "v23-size-strong",
    "v23-size-wet",
    "v23-size-both",
    "v24-bluff-3bet",
    "v25-barrel-bluff",
    "v26-fold-premium-extreme",
    "v27-river-overbet",
    "v28-optimal-sizing",
    "v29-iso-wider-range",
    "v30-size-scaled-call",
):
    HISTORICAL_PRIOR_ON_FLAGS[_preset] = HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-wide"]


@dataclass(frozen=True)
class ProbeComparison:
    label: str
    baseline: dict[str, object]
    treatment: dict[str, object]


def _real_flag_value(name: str, value: bool) -> object:
    if name in PSEUDO_FLAGS:
        return value
    if name in _NON_BOOLEAN_FLAG_ON_VALUES:
        return _NON_BOOLEAN_FLAG_ON_VALUES[name] if value else _NON_BOOLEAN_FLAG_OFF_VALUES[name]
    return value


def _state_for_flags(flag_names: list[str], value: bool) -> dict[str, object]:
    return {name: _real_flag_value(name, value) for name in flag_names}


def _current_state_for_flags(flag_names: list[str]) -> dict[str, object]:
    state = {}
    for name in flag_names:
        if name == PSEUDO_OPPONENT_AWARE:
            state[name] = True
        else:
            value = getattr(abc_bot, name)
            state[name] = set(value) if name in _NON_BOOLEAN_FLAG_ON_VALUES else value
    return state


def _historical_baseline_state(preset: str) -> dict[str, object]:
    if preset == "v9-wide-3bet":
        raise ValueError(
            "v9 predates the v10 opponent-aware calling rule, but this probe always runs with "
            "opponent archetypes. Use --comparison current for v9, or add an explicit opponent-aware off arm."
        )
    if preset not in HISTORICAL_PRIOR_ON_FLAGS:
        raise ValueError(f"no historical comparison profile for {preset}")
    state = {name: _real_flag_value(name, False) for name in ALL_COMPARISON_FLAGS}
    for name in HISTORICAL_PRIOR_ON_FLAGS[preset]:
        state[name] = _real_flag_value(name, True)
    return state


def _build_comparison(preset: str, comparison: Literal["current", "historical", "ablation"]) -> ProbeComparison:
    flag_names, _ = _all_test_groups()[preset]
    if comparison == "current":
        return ProbeComparison(
            "current defaults overlay",
            _state_for_flags(flag_names, False),
            _state_for_flags(flag_names, True),
        )
    if comparison == "ablation":
        baseline = _current_state_for_flags(flag_names)
        treatment = baseline | _state_for_flags(flag_names, False)
        return ProbeComparison("current full-model ablation (without rule - full)", baseline, treatment)
    baseline = _historical_baseline_state(preset)
    treatment = baseline | _state_for_flags(flag_names, True)
    return ProbeComparison("historical at-introduction flags", baseline, treatment)


def _apply_flag_state(state: dict[str, object]) -> None:
    for name, real_value in state.items():
        if name in PSEUDO_FLAGS:
            continue
        if name in _NON_BOOLEAN_FLAG_ON_VALUES:
            real_value = set(real_value)
        setattr(abc_bot, name, real_value)
    if "USE_WIDE_VALUE_3BET" in state:
        _sync_value_3bet(bool(state["USE_WIDE_VALUE_3BET"]))
    if MULTIWAY_SUBFLAGS & state.keys() and "MULTIWAY_AWARE" not in state:
        abc_bot.MULTIWAY_AWARE = any(bool(getattr(abc_bot, name)) for name in MULTIWAY_SUBFLAGS)


def _restore_flags(original: dict[str, object]) -> None:
    for name, value in original.items():
        if name in PSEUDO_FLAGS:
            continue
        setattr(abc_bot, name, value)
    if "USE_WIDE_VALUE_3BET" in original:
        _sync_value_3bet(original["USE_WIDE_VALUE_3BET"])
    if MULTIWAY_SUBFLAGS & original.keys() and "MULTIWAY_AWARE" not in original:
        abc_bot.MULTIWAY_AWARE = any(bool(getattr(abc_bot, name)) for name in MULTIWAY_SUBFLAGS)


def _make_table() -> Table:
    table = Table(
        small_blind=1.0,
        big_blind=2.0,
        max_seats=MAX_SEATS,
        rake_percent=RAKE_PERCENT,
        rake_cap_bb=RAKE_CAP_BB,
    )
    for seat in range(1, MAX_SEATS + 1):
        table.add_player(seat=seat, name=("Hero" if seat == HERO_SEAT else f"Bot{seat}"), stack=STARTING_STACK)
    return table


def _reset_stacks(table: Table) -> None:
    for player in table.players.values():
        player.stack = STARTING_STACK
        player.sitting_out = False


def _hero_net(hand) -> float:
    invested = hand.players[HERO_SEAT].total_contributed
    payout = hand.result.payouts.get(HERO_SEAT, 0.0) if hand.result else 0.0
    return payout - invested


def _force_next_board_card(hand, card_str: str) -> bool:
    if hand.finished or len(hand.board) >= 5:
        return False
    for i, card in enumerate(hand.deck.cards):
        if str(card) == card_str:
            chosen = hand.deck.cards.pop(i)
            hand.deck.cards.insert(0, chosen)
            return True
    return False


def _available_next_cards(*hands) -> list[str]:
    for hand in hands:
        if not hand.finished and len(hand.board) < 5:
            return [str(card) for card in hand.deck.cards]
    return []


def _hero_opponent_archetypes(hand, turnover: TableTurnover, flag_state: dict[str, object]) -> dict[int, str] | None:
    if flag_state.get(PSEUDO_OPPONENT_AWARE, True) is False:
        return None
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    return {s: turnover.archetype_for(s) for s in bot_seats if hand.players[s].in_hand}


def _choose_and_apply(
    hand,
    seat: int,
    hand_index: int,
    guard: int,
    turnover: TableTurnover,
    flag_state: dict[str, object],
) -> tuple[str, float | None]:
    if seat == HERO_SEAT:
        _apply_flag_state(flag_state)
        opponent_archetypes = _hero_opponent_archetypes(hand, turnover, flag_state)
        action, amount = choose_abc_action(hand, seat, opponent_archetypes=opponent_archetypes)
    else:
        archetype = turnover.archetype_for(seat)
        bot_seed = _common_seed(42, hand_index, BOT_ACTION_SEED_STREAM, guard, seat)
        action, amount = choose_bot_action(hand, seat, archetype=archetype, seed=bot_seed)

    try:
        hand.apply_action(seat, action, amount)
    except IllegalAction:
        action, amount = "fold", None
        hand.apply_action(seat, "fold")
    return action, amount


def _continue_to_finish(
    hand,
    hand_index: int,
    turnover: TableTurnover,
    flag_state: dict[str, object],
    branch_id: int = 0,
) -> float | None:
    guard = 0
    while not hand.finished and guard < 500:
        seat = hand.current_actor()
        if seat is None:
            break
        if seat == HERO_SEAT:
            _apply_flag_state(flag_state)
            opponent_archetypes = _hero_opponent_archetypes(hand, turnover, flag_state)
            action, amount = choose_abc_action(hand, seat, opponent_archetypes=opponent_archetypes)
        else:
            archetype = turnover.archetype_for(seat)
            bot_seed = _common_seed(42, hand_index, BOT_ACTION_SEED_STREAM, guard, seat, branch_id)
            action, amount = choose_bot_action(hand, seat, archetype=archetype, seed=bot_seed)
        try:
            hand.apply_action(seat, action, amount)
        except IllegalAction:
            hand.apply_action(seat, "fold")
        guard += 1
    return _hero_net(hand) if hand.finished else None


def _stats(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    ci = 1.96 * stdev / (len(values) ** 0.5) * 100 if len(values) > 1 else 0.0
    return mean * 100, ci


def _run_probe_chunk(
    baseline_state: dict[str, object],
    treatment_state: dict[str, object],
    base_table: Table,
    treat_table: Table,
    base_turnover: TableTurnover,
    treat_turnover: TableTurnover,
    start_hand_index: int,
    n_hands: int,
    random_deltas: list[float],
    enum_deltas: list[float],
    branch_counts: list[int],
) -> int:
    divergent = 0
    for hand_index in range(start_hand_index, start_hand_index + n_hands):
        _reset_stacks(base_table)
        _reset_stacks(treat_table)
        deck_seed = _common_seed(42, hand_index, DECK_SEED_STREAM)
        base_hand = base_table.start_new_hand(deck_seed=deck_seed)
        treat_hand = treat_table.start_new_hand(deck_seed=deck_seed)

        split = False
        guard = 0
        while not base_hand.finished and not treat_hand.finished and guard < 500:
            base_seat = base_hand.current_actor()
            treat_seat = treat_hand.current_actor()
            if base_seat != treat_seat or base_seat is None:
                break

            base_before = copy.deepcopy(base_hand)
            treat_before = copy.deepcopy(treat_hand)
            base_action = _choose_and_apply(base_hand, base_seat, hand_index, guard, base_turnover, baseline_state)
            treat_action = _choose_and_apply(treat_hand, treat_seat, hand_index, guard, treat_turnover, treatment_state)

            same_action = base_action[0] == treat_action[0] and (base_action[1] == treat_action[1])
            if not same_action and base_seat == HERO_SEAT:
                split = True
                divergent += 1

                random_base = copy.deepcopy(base_hand)
                random_treat = copy.deepcopy(treat_hand)
                rb = _continue_to_finish(random_base, hand_index, base_turnover, baseline_state, branch_id=0)
                rt = _continue_to_finish(random_treat, hand_index, treat_turnover, treatment_state, branch_id=0)
                if rb is not None and rt is not None:
                    random_deltas.append(rt - rb)

                cards = _available_next_cards(base_hand, treat_hand)
                branch_counts.append(len(cards))
                branch_deltas: list[float] = []
                for branch_id, card_str in enumerate(cards, start=1):
                    b = copy.deepcopy(base_hand)
                    t = copy.deepcopy(treat_hand)
                    _force_next_board_card(b, card_str)
                    _force_next_board_card(t, card_str)
                    nb = _continue_to_finish(b, hand_index, base_turnover, baseline_state, branch_id=branch_id)
                    nt = _continue_to_finish(t, hand_index, treat_turnover, treatment_state, branch_id=branch_id)
                    if nb is not None and nt is not None:
                        branch_deltas.append(nt - nb)
                if branch_deltas:
                    enum_deltas.append(sum(branch_deltas) / len(branch_deltas))
                elif rb is not None and rt is not None:
                    enum_deltas.append(rt - rb)
                break

            # If a non-hero action somehow differs, restore and just continue
            # both worlds independently; this probe is about hero-rule splits.
            if not same_action:
                base_hand = base_before
                treat_hand = treat_before
                break
            guard += 1

        if not split:
            random_deltas.append(0.0)
            enum_deltas.append(0.0)
    return divergent


def _parse_archetypes(value: str | None) -> list[str] | None:
    if not value:
        return None
    archetypes = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(archetypes) - set(ARCHETYPE_POOL))
    if unknown:
        raise ValueError(f"unknown archetypes: {', '.join(unknown)}; options: {', '.join(ARCHETYPE_POOL)}")
    return archetypes or None


def _new_probe_state(allowed_archetypes: list[str] | None) -> tuple[Table, Table, TableTurnover, TableTurnover]:
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    return (
        _make_table(),
        _make_table(),
        TableTurnover(bot_seats, rng_seed=42, allowed_archetypes=allowed_archetypes),
        TableTurnover(bot_seats, rng_seed=42, allowed_archetypes=allowed_archetypes),
    )


def _print_probe_summary(
    label: str,
    preset: str,
    n_hands: int,
    divergent: int,
    branch_counts: list[int],
    random_deltas: list[float],
    enum_deltas: list[float],
    elapsed: float,
) -> None:
    random_delta, random_ci = _stats(random_deltas)
    enum_delta, enum_ci = _stats(enum_deltas)
    shrink = random_ci / enum_ci if enum_ci else float("inf")
    avg_branches = statistics.mean(branch_counts) if branch_counts else 0.0
    print(f"{label} ({preset})")
    print(f"hands: {n_hands}, divergent hero hands: {divergent} ({divergent / n_hands * 100:.2f}%)")
    print(f"avg next-card branches when divergent: {avg_branches:.1f}")
    print(f"random continuation delta: {random_delta:+.2f} bb/100 (95% CI +/- {random_ci:.2f})")
    print(f"next-card enumerated delta: {enum_delta:+.2f} bb/100 (95% CI +/- {enum_ci:.2f})")
    print(f"CI shrink from enumeration: {shrink:.2f}x")
    print(f"elapsed: {elapsed:.2f}s")


def _original_state_for(comparison: ProbeComparison) -> dict[str, object]:
    names = set(comparison.baseline) | set(comparison.treatment) | {"MULTIWAY_AWARE"}
    return {name: getattr(abc_bot, name) for name in names if hasattr(abc_bot, name)}


def run_probe(
    preset: str,
    n_hands: int,
    comparison_mode: Literal["current", "historical", "ablation"],
    allowed_archetypes: list[str] | None,
) -> None:
    _, label = _all_test_groups()[preset]
    comparison = _build_comparison(preset, comparison_mode)
    original = _original_state_for(comparison)
    base_table, treat_table, base_turnover, treat_turnover = _new_probe_state(allowed_archetypes)

    random_deltas: list[float] = []
    enum_deltas: list[float] = []
    divergent = 0
    branch_counts: list[int] = []
    t0 = time.perf_counter()
    try:
        divergent += _run_probe_chunk(
            comparison.baseline,
            comparison.treatment,
            base_table,
            treat_table,
            base_turnover,
            treat_turnover,
            0,
            n_hands,
            random_deltas,
            enum_deltas,
            branch_counts,
        )
    finally:
        _restore_flags(original)

    archetype_label = ",".join(allowed_archetypes) if allowed_archetypes else "population"
    print(f"comparison: {comparison.label}; archetypes={archetype_label}", flush=True)
    _print_probe_summary(label, preset, n_hands, divergent, branch_counts, random_deltas, enum_deltas, time.perf_counter() - t0)


def _adaptive_stop_reason(
    n_hands: int,
    divergent: int,
    enum_delta: float,
    enum_ci: float,
    *,
    min_hands: int,
    max_hands: int,
    max_zero_divergent_hands: int,
    min_divergent: int,
    max_divergent: int,
    target_ci: float,
    effect_ratio: float,
) -> str | None:
    if n_hands >= max_hands:
        return "max_hands"
    if divergent >= max_divergent:
        return "max_divergent"
    if divergent == 0 and max_zero_divergent_hands > 0 and n_hands >= max_zero_divergent_hands:
        return "no_divergent_hands"
    if n_hands < min_hands or divergent < min_divergent:
        return None
    abs_delta = abs(enum_delta)
    if enum_delta < 0 and enum_ci <= abs_delta:
        return "confirmed_negative"
    if enum_delta > 0 and enum_ci <= abs_delta * effect_ratio:
        return "confirmed_positive"
    if enum_ci <= target_ci and enum_ci <= abs_delta * effect_ratio:
        return "confirmed_precise"
    if enum_ci <= target_ci and abs(enum_delta) < target_ci:
        return "inconclusive_small_effect"
    return None


def run_adaptive_probe(
    preset: str,
    *,
    comparison_mode: Literal["current", "historical", "ablation"],
    target_ci: float,
    effect_ratio: float,
    min_hands: int,
    max_hands: int,
    max_zero_divergent_hands: int,
    chunk_size: int,
    min_divergent: int,
    max_divergent: int,
    allowed_archetypes: list[str] | None,
) -> None:
    _, label = _all_test_groups()[preset]
    comparison = _build_comparison(preset, comparison_mode)
    original = _original_state_for(comparison)
    base_table, treat_table, base_turnover, treat_turnover = _new_probe_state(allowed_archetypes)
    random_deltas: list[float] = []
    enum_deltas: list[float] = []
    branch_counts: list[int] = []
    divergent = 0
    n_hands = 0
    t0 = time.perf_counter()
    stop_reason = None
    archetype_label = ",".join(allowed_archetypes) if allowed_archetypes else "population"
    print(
        f"adaptive chance-enumeration: {label} ({preset}), "
        f"comparison={comparison.label}, "
        f"archetypes={archetype_label}, "
        f"target_ci={target_ci}, effect_ratio={effect_ratio}, min/max hands={min_hands}/{max_hands}, "
        f"max_zero_divergent_hands={max_zero_divergent_hands}, "
        f"min/max divergent={min_divergent}/{max_divergent}, chunk={chunk_size}",
        flush=True,
    )
    try:
        while n_hands < max_hands:
            this_chunk = min(chunk_size, max_hands - n_hands)
            divergent += _run_probe_chunk(
                comparison.baseline,
                comparison.treatment,
                base_table,
                treat_table,
                base_turnover,
                treat_turnover,
                n_hands,
                this_chunk,
                random_deltas,
                enum_deltas,
                branch_counts,
            )
            n_hands += this_chunk
            random_delta, random_ci = _stats(random_deltas)
            enum_delta, enum_ci = _stats(enum_deltas)
            elapsed = time.perf_counter() - t0
            print(
                f"progress hands={n_hands} divergent={divergent} ({divergent / n_hands * 100:.2f}%) "
                f"random_delta={random_delta:+.2f} random_ci={random_ci:.2f} "
                f"enum_delta={enum_delta:+.2f} enum_ci={enum_ci:.2f} elapsed={elapsed:.1f}s",
                flush=True,
            )
            stop_reason = _adaptive_stop_reason(
                n_hands,
                divergent,
                enum_delta,
                enum_ci,
                min_hands=min_hands,
                max_hands=max_hands,
                max_zero_divergent_hands=max_zero_divergent_hands,
                min_divergent=min_divergent,
                max_divergent=max_divergent,
                target_ci=target_ci,
                effect_ratio=effect_ratio,
            )
            if stop_reason:
                break
    finally:
        _restore_flags(original)

    print(f"stop_reason: {stop_reason or 'finished'}", flush=True)
    _print_probe_summary(label, preset, n_hands, divergent, branch_counts, random_deltas, enum_deltas, time.perf_counter() - t0)


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("preset", nargs="?", default="v16-iso-limpers")
    parser.add_argument("n_hands", nargs="?", type=int, default=1000)
    parser.add_argument(
        "--comparison",
        choices=("current", "historical", "ablation"),
        default="current",
        help=(
            "current overlays only the tested flags on today's defaults; "
            "historical resets known A/B flags to the preset's at-introduction context; "
            "ablation compares today's full model against full model with the tested flags disabled"
        ),
    )
    parser.add_argument("--adaptive", action="store_true", help="run chunks until effect-strength/precision or hard-cap stop criteria are met")
    parser.add_argument("--archetypes", help="comma-separated opponent archetypes to seat; omitted means the real population mix")
    parser.add_argument("--target-ci", type=float, default=1.0)
    parser.add_argument("--effect-ratio", type=float, default=0.5, help="positive effect is confirmed when CI <= abs(delta) * this ratio")
    parser.add_argument("--min-hands", type=int, default=10_000)
    parser.add_argument("--max-hands", type=int, default=500_000)
    parser.add_argument("--max-zero-divergent-hands", type=int, default=50_000)
    parser.add_argument("--chunk-size", type=int, default=2_000)
    parser.add_argument("--min-divergent", type=int, default=30)
    parser.add_argument("--max-divergent", type=int, default=2_000)
    args = parser.parse_args()
    preset = args.preset
    groups = _all_test_groups()
    if preset not in groups:
        raise SystemExit(f"unknown preset {preset}; options: {', '.join(groups)}")
    try:
        allowed_archetypes = _parse_archetypes(args.archetypes)
        if args.adaptive:
            run_adaptive_probe(
                preset,
                comparison_mode=args.comparison,
                target_ci=args.target_ci,
                effect_ratio=args.effect_ratio,
                min_hands=args.min_hands,
                max_hands=args.max_hands,
                max_zero_divergent_hands=args.max_zero_divergent_hands,
                chunk_size=args.chunk_size,
                min_divergent=args.min_divergent,
                max_divergent=args.max_divergent,
                allowed_archetypes=allowed_archetypes,
            )
        else:
            run_probe(preset, args.n_hands, args.comparison, allowed_archetypes)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
