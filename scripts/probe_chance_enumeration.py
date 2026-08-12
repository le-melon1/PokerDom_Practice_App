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

sys.path.insert(0, str(__file__).rsplit("/scripts/", 1)[0])

import backend.bots.abc_bot as abc_bot
from backend.bots.abc_bot import choose_abc_action
from backend.bots.behavior_clone import choose_bot_action
from backend.engine.cards_import import Card
from backend.engine.hand import IllegalAction
from backend.engine.table import Table
from backend.sessions.live_dynamics import TableTurnover
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
    "v11-multiway-aware": (
        ["MULTIWAY_NARROW_CALL_RANGE", "MULTIWAY_DISABLE_AIR_CBET", "MULTIWAY_DISABLE_LOOSE_CALL", "MULTIWAY_AWARE"],
        "v11 multiway aware",
    ),
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


def _all_test_groups() -> dict[str, tuple[list[str], str]]:
    return {**PRESET_FLAG_GROUPS, **EXTRA_TEST_GROUPS}


def _apply_flags(flag_names: list[str], value: bool) -> None:
    for name in flag_names:
        if name in _NON_BOOLEAN_FLAG_ON_VALUES:
            real_value = _NON_BOOLEAN_FLAG_ON_VALUES[name] if value else _NON_BOOLEAN_FLAG_OFF_VALUES[name]
        else:
            real_value = value
        setattr(abc_bot, name, real_value)
    if "USE_WIDE_VALUE_3BET" in flag_names:
        _sync_value_3bet(value)


def _restore_flags(original: dict[str, object]) -> None:
    for name, value in original.items():
        setattr(abc_bot, name, value)
    if "USE_WIDE_VALUE_3BET" in original:
        _sync_value_3bet(original["USE_WIDE_VALUE_3BET"])


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


def _choose_and_apply(hand, seat: int, hand_index: int, guard: int, turnover: TableTurnover, flag_names: list[str], flag_value: bool) -> tuple[str, float | None]:
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    if seat == HERO_SEAT:
        _apply_flags(flag_names, flag_value)
        opponent_archetypes = {s: turnover.archetype_for(s) for s in bot_seats if hand.players[s].in_hand}
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


def _continue_to_finish(hand, hand_index: int, turnover: TableTurnover, flag_names: list[str], flag_value: bool, branch_id: int = 0) -> float | None:
    guard = 0
    while not hand.finished and guard < 500:
        seat = hand.current_actor()
        if seat is None:
            break
        if seat == HERO_SEAT:
            _apply_flags(flag_names, flag_value)
            bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
            opponent_archetypes = {s: turnover.archetype_for(s) for s in bot_seats if hand.players[s].in_hand}
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
    flag_names: list[str],
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
            base_action = _choose_and_apply(base_hand, base_seat, hand_index, guard, base_turnover, flag_names, False)
            treat_action = _choose_and_apply(treat_hand, treat_seat, hand_index, guard, treat_turnover, flag_names, True)

            same_action = base_action[0] == treat_action[0] and (base_action[1] == treat_action[1])
            if not same_action and base_seat == HERO_SEAT:
                split = True
                divergent += 1

                random_base = copy.deepcopy(base_hand)
                random_treat = copy.deepcopy(treat_hand)
                rb = _continue_to_finish(random_base, hand_index, base_turnover, flag_names, False, branch_id=0)
                rt = _continue_to_finish(random_treat, hand_index, treat_turnover, flag_names, True, branch_id=0)
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
                    nb = _continue_to_finish(b, hand_index, base_turnover, flag_names, False, branch_id=branch_id)
                    nt = _continue_to_finish(t, hand_index, treat_turnover, flag_names, True, branch_id=branch_id)
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


def _new_probe_state() -> tuple[Table, Table, TableTurnover, TableTurnover]:
    return (
        _make_table(),
        _make_table(),
        TableTurnover([s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT], rng_seed=42),
        TableTurnover([s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT], rng_seed=42),
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


def run_probe(preset: str, n_hands: int) -> None:
    flag_names, label = _all_test_groups()[preset]
    original = {name: getattr(abc_bot, name) for name in flag_names}
    base_table, treat_table, base_turnover, treat_turnover = _new_probe_state()

    random_deltas: list[float] = []
    enum_deltas: list[float] = []
    divergent = 0
    branch_counts: list[int] = []
    t0 = time.perf_counter()
    try:
        divergent += _run_probe_chunk(
            flag_names,
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

    _print_probe_summary(label, preset, n_hands, divergent, branch_counts, random_deltas, enum_deltas, time.perf_counter() - t0)


def _adaptive_stop_reason(
    n_hands: int,
    divergent: int,
    enum_delta: float,
    enum_ci: float,
    *,
    min_hands: int,
    max_hands: int,
    min_divergent: int,
    max_divergent: int,
    target_ci: float,
    effect_ratio: float,
) -> str | None:
    if n_hands >= max_hands:
        return "max_hands"
    if divergent >= max_divergent:
        return "max_divergent"
    if n_hands < min_hands or divergent < min_divergent:
        return None
    if enum_ci <= target_ci and enum_ci <= abs(enum_delta) * effect_ratio:
        return "confirmed"
    if enum_ci <= target_ci and abs(enum_delta) < target_ci:
        return "inconclusive_small_effect"
    return None


def run_adaptive_probe(
    preset: str,
    *,
    target_ci: float,
    effect_ratio: float,
    min_hands: int,
    max_hands: int,
    chunk_size: int,
    min_divergent: int,
    max_divergent: int,
) -> None:
    flag_names, label = _all_test_groups()[preset]
    original = {name: getattr(abc_bot, name) for name in flag_names}
    base_table, treat_table, base_turnover, treat_turnover = _new_probe_state()
    random_deltas: list[float] = []
    enum_deltas: list[float] = []
    branch_counts: list[int] = []
    divergent = 0
    n_hands = 0
    t0 = time.perf_counter()
    stop_reason = None
    print(
        f"adaptive chance-enumeration: {label} ({preset}), "
        f"target_ci={target_ci}, effect_ratio={effect_ratio}, min/max hands={min_hands}/{max_hands}, "
        f"min/max divergent={min_divergent}/{max_divergent}, chunk={chunk_size}",
        flush=True,
    )
    try:
        while n_hands < max_hands:
            this_chunk = min(chunk_size, max_hands - n_hands)
            divergent += _run_probe_chunk(
                flag_names,
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
    parser.add_argument("--adaptive", action="store_true", help="run chunks until precision/effect or hard-cap stop criteria are met")
    parser.add_argument("--target-ci", type=float, default=1.0)
    parser.add_argument("--effect-ratio", type=float, default=0.5, help="confirmed when CI <= abs(delta) * this ratio")
    parser.add_argument("--min-hands", type=int, default=10_000)
    parser.add_argument("--max-hands", type=int, default=500_000)
    parser.add_argument("--chunk-size", type=int, default=2_000)
    parser.add_argument("--min-divergent", type=int, default=30)
    parser.add_argument("--max-divergent", type=int, default=2_000)
    args = parser.parse_args()
    preset = args.preset
    groups = _all_test_groups()
    if preset not in groups:
        raise SystemExit(f"unknown preset {preset}; options: {', '.join(groups)}")
    if args.adaptive:
        run_adaptive_probe(
            preset,
            target_ci=args.target_ci,
            effect_ratio=args.effect_ratio,
            min_hands=args.min_hands,
            max_hands=args.max_hands,
            chunk_size=args.chunk_size,
            min_divergent=args.min_divergent,
            max_divergent=args.max_divergent,
        )
    else:
        run_probe(preset, args.n_hands)


if __name__ == "__main__":
    main()
