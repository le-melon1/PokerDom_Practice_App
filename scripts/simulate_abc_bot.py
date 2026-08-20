"""Runs the Tier-1-only ABC bot (backend/bots/abc_bot.py) through many hands
at a 6-max table against the same ML behavior-clone bots used in the live
practice app, with a population-weighted archetype mix and real session-length
turnover (backend/sessions/live_dynamics.py) -- the same opposition the guide's
own Tier 1/2/3 EV numbers were computed against, not a synthetic one.

Reports bb/100 with and without PokerDom's real rake (5%, capped at 5bb, no
flop no drop) as two separate runs, directly testing the guide's own
disclaimer ("рейк нигде выше не учтён... реальная прибыльность будет ниже").

Usage: python3 scripts/simulate_abc_bot.py [n_hands] [--no-rake-only] [--both]
Default: calibrates on a small sample first, then runs a sized batch.

2026-08-08: a real chip-conservation bug in backend/engine/hand.py was found
and fixed the same day -- a side-pot layer whose only-ever contributor later
folded (the classic "uncalled bet" case, e.g. a big bet nobody could fully
call, followed by the bettor folding to a subsequent street's action) was
silently dropped instead of refunded. Confirmed with scripts/
smoke_test_table.py (random actions lost hundreds of chips within a handful
of hands) AND with this project's own real bots (0.3-0.4% or so of hands
triggered it in early spot-checks, before precise measurement was abandoned
as not worth the time; 20,000 real-bot hands post-fix showed zero further
violations). Every bb/100 number measured before this date carries some
amount of additional, previously-undocumented noise from this source on top
of the reported 95% CI -- almost certainly small relative to the sampling
noise already being reported (the bug needs a fairly specific multi-way
all-in-then-fold shape to trigger), but not something the CI itself
accounted for. Numbers measured from this date forward do not have this
caveat.
"""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.bots.abc_bot as abc_bot
from backend.bots.abc_bot import choose_abc_action
from backend.bots.behavior_clone import choose_bot_action
from backend.dossier import TableDossier
from backend.engine.hand import IllegalAction
from backend.engine.table import Table
from backend.sessions.live_dynamics import TableTurnover

HERO_SEAT = 1
RAKE_PERCENT = 0.05
RAKE_CAP_BB = 5.0
STARTING_STACK = 200.0
MAX_SEATS = 6
DECK_SEED_STREAM = 1
BOT_ACTION_SEED_STREAM = 2
HERO_HAND_SEED_STREAM = 3
OPPONENT_HAND_SEED_STREAM = 4
COMMON_RANDOM = False


def _common_seed(base_seed: int, hand_index: int, stream: int, *parts: int) -> int:
    """Stable per-hand/per-decision seed for common-random-number A/B tests."""
    value = base_seed & 0xFFFFFFFF
    for part in (hand_index, stream, *parts):
        value ^= (part + 0x9E3779B9 + ((value << 6) & 0xFFFFFFFF) + (value >> 2)) & 0xFFFFFFFF
        value &= 0xFFFFFFFF
    return value


def run_batch(
    n_hands: int, rake_percent: float, rake_cap_bb: float, seed: int,
    opponent_aware: bool = True, archetype_source: str = "ground_truth",
    common_random: bool | None = None,
) -> dict:
    """archetype_source: "ground_truth" feeds choose_abc_action the archetype
    the ML bot was actually SEATED with (a ceiling test -- the live app can't
    know this). "dossier" instead feeds it backend/dossier.py's session-scoped
    ESTIMATE, built the same noisy way the real app would (no minimum-hands
    gate, resets when a seat turns over) -- see run_dossier_realism_comparison
    for how much of the ground-truth benefit survives under that realism."""
    table = Table(
        small_blind=1.0, big_blind=2.0, max_seats=MAX_SEATS,
        rake_percent=rake_percent, rake_cap_bb=rake_cap_bb,
    )
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    turnover = TableTurnover(bot_seats, rng_seed=seed)
    dossier = TableDossier()
    for seat in bot_seats:
        dossier.reset_seat(seat)

    for seat in range(1, MAX_SEATS + 1):
        table.add_player(seat=seat, name=("Hero" if seat == HERO_SEAT else f"Bot{seat}"), stack=STARTING_STACK)

    use_common_random = COMMON_RANDOM if common_random is None else common_random
    hero_net_total = 0.0
    hero_net_per_hand: list[float] = []
    hero_net_per_hand_normal: list[float] = []  # excludes monster pots
    normal_net_by_hand_index: list[float | None] = []
    hero_vpip_hands = 0
    hero_pfr_hands = 0
    hands_completed = 0
    monster_pots = 0  # pots > 50bb -- flags hands where the ML bots' known
    # stack-unaware sizing model ran away with repeated large raises (see
    # scripts/simulate_abc_bot.py's usage docstring / final report)

    for hand_index in range(n_hands):
        normal_net_by_hand_index.append(None)
        if table.players[HERO_SEAT].stack <= 0:
            table.players[HERO_SEAT].stack = STARTING_STACK  # rebuy, keep sim running

        try:
            deck_seed = _common_seed(seed, hand_index, DECK_SEED_STREAM) if use_common_random else None
            hand = table.start_new_hand(deck_seed=deck_seed)
        except RuntimeError:
            for p in table.players.values():
                if p.stack <= 0:
                    p.stack = STARTING_STACK
                    p.sitting_out = False
            continue

        guard = 0
        while not hand.finished and guard < 500:
            seat = hand.current_actor()
            if seat is None:
                break
            if seat == HERO_SEAT:
                if opponent_aware:
                    if archetype_source == "dossier":
                        opponent_archetypes = {
                            s: dossier.by_seat[s].style for s in bot_seats if hand.players[s].in_hand
                        }
                    else:
                        opponent_archetypes = {
                            s: turnover.archetype_for(s) for s in bot_seats if hand.players[s].in_hand
                        }
                else:
                    opponent_archetypes = None
                action, amount = choose_abc_action(hand, seat, opponent_archetypes=opponent_archetypes)
            else:
                archetype = turnover.archetype_for(seat)
                freq_tier = turnover.freq_tier_for(seat)
                bot_seed = _common_seed(seed, hand_index, BOT_ACTION_SEED_STREAM, guard, seat) if use_common_random else None
                action, amount = choose_bot_action(hand, seat, archetype=archetype, freq_tier=freq_tier, seed=bot_seed)
            try:
                hand.apply_action(seat, action, amount)
            except IllegalAction:
                hand.apply_action(seat, "fold")
            guard += 1

        if not hand.finished:
            continue

        hands_completed += 1
        hero_invested = hand.players[HERO_SEAT].total_contributed
        hero_payout = hand.result.payouts.get(HERO_SEAT, 0.0) if hand.result else 0.0
        hero_net = hero_payout - hero_invested
        hero_net_total += hero_net
        hero_net_per_hand.append(hero_net)
        if sum(p.total_contributed for p in hand.players.values()) > 50:
            monster_pots += 1
        else:
            hero_net_per_hand_normal.append(hero_net)
            normal_net_by_hand_index[hand_index] = hero_net

        preflop_actions = [a for a in hand.actions if a.street == "preflop" and a.seat == HERO_SEAT]
        if any(a.action in ("calls", "bets", "raises") for a in preflop_actions):
            hero_vpip_hands += 1
        if any(a.action == "raises" for a in preflop_actions):
            hero_pfr_hands += 1

        dossier.record_hand(hand)

        seat_stacks = {seat: p.stack for seat, p in hand.players.items() if seat != HERO_SEAT}
        turned_over = turnover.after_hand(seat_stacks, STARTING_STACK)
        for seat, did_turn_over in turned_over.items():
            if did_turn_over:
                table.players[seat].stack = STARTING_STACK
                table.players[seat].sitting_out = False
                dossier.reset_seat(seat)  # new occupant -- dossier must not leak the old one's stats

    n = hands_completed
    mean = hero_net_total / n if n else 0.0
    stdev = statistics.pstdev(hero_net_per_hand) if n > 1 else 0.0
    sem = stdev / (n ** 0.5) if n else 0.0  # standard error of the per-hand mean
    ci95_bb100 = 1.96 * sem * 100  # +/- half-width of the 95% CI, in bb/100
    sorted_net = sorted(hero_net_per_hand)
    median = sorted_net[n // 2] if n else 0.0
    win_hand_rate = sum(1 for x in hero_net_per_hand if x > 0) / n if n else 0.0

    n_normal = len(hero_net_per_hand_normal)
    mean_normal = (sum(hero_net_per_hand_normal) / n_normal) if n_normal else 0.0
    stdev_normal = statistics.pstdev(hero_net_per_hand_normal) if n_normal > 1 else 0.0
    ci95_normal = 1.96 * (stdev_normal / (n_normal ** 0.5)) * 100 if n_normal else 0.0

    return {
        "hands": n,
        "hero_net_bb": hero_net_total,
        "bb_per_100": mean * 100,
        "bb_per_100_ci95": ci95_bb100,
        "median_hand_bb": median,
        "win_hand_rate": win_hand_rate,
        "monster_pot_rate": monster_pots / n if n else 0.0,
        "bb_per_100_excl_monsters": mean_normal * 100,
        "bb_per_100_excl_monsters_ci95": ci95_normal,
        "hero_vpip": hero_vpip_hands / n if n else 0.0,
        "hero_pfr": hero_pfr_hands / n if n else 0.0,
        "normal_net_by_hand_index": normal_net_by_hand_index,
        "common_random": use_common_random,
    }


def _paired_delta_stats(baseline: dict, treatment: dict) -> dict:
    baseline_hands = baseline.get("normal_net_by_hand_index") or []
    treatment_hands = treatment.get("normal_net_by_hand_index") or []
    deltas = [
        treatment_net - baseline_net
        for baseline_net, treatment_net in zip(baseline_hands, treatment_hands)
        if baseline_net is not None and treatment_net is not None
    ]
    n = len(deltas)
    if not n:
        return {"n": 0, "delta_bb100": 0.0, "ci95_bb100": 0.0}
    mean = sum(deltas) / n
    stdev = statistics.pstdev(deltas) if n > 1 else 0.0
    ci95 = 1.96 * (stdev / (n ** 0.5)) * 100 if n > 1 else 0.0
    return {"n": n, "delta_bb100": mean * 100, "ci95_bb100": ci95}


def _print_paired_delta(label: str, baseline: dict, treatment: dict) -> None:
    if not (baseline.get("common_random") and treatment.get("common_random")):
        return
    paired = _paired_delta_stats(baseline, treatment)
    independent_ci = (
        baseline["bb_per_100_excl_monsters_ci95"] ** 2
        + treatment["bb_per_100_excl_monsters_ci95"] ** 2
    ) ** 0.5
    ci_ratio = independent_ci / paired["ci95_bb100"] if paired["ci95_bb100"] else float("inf")
    print(
        f"{label} paired delta: {paired['delta_bb100']:+.2f} bb/100 "
        f"(95% CI +/- {paired['ci95_bb100']:.2f}, paired non-monster hands: {paired['n']})"
    )
    print(
        f"{label} CI shrink: independent +/- {independent_ci:.2f} -> paired +/- {paired['ci95_bb100']:.2f} "
        f"({ci_ratio:.2f}x tighter)"
    )


def run_opponent_aware_comparison(n_hands: int):
    """A/B test: does letting the bot loosen its calling bar against known
    loose/weak archetypes (LOOSE_ARCHETYPES in abc_bot.py) actually help, or
    is the extra complexity not worth it? Both runs use real rake (the
    realistic scenario) and ground-truth archetypes (a ceiling test -- see
    choose_abc_action's docstring for how this differs from the live app,
    which would use the session dossier's estimate instead)."""
    print(f"\n[1/2] {n_hands} hands, opponent-UNAWARE (baseline)...")
    t0 = time.time()
    unaware = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=False)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[2/2] {n_hands} hands, opponent-AWARE (loosen vs known loose archetypes)...")
    t0 = time.time()
    aware = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print("\n" + "=" * 60)
    print("OPPONENT-AWARENESS A/B TEST (both WITH real rake)")
    print("=" * 60)
    for label, r in (("Opponent-unaware (baseline)", unaware), ("Opponent-aware (loosen vs loose archetypes)", aware)):
        print(f"\n{label}:")
        print(f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})")
        print(f"  monster pots: {r['monster_pot_rate']*100:.2f}%   hero VPIP/PFR: {r['hero_vpip']*100:.1f}%/{r['hero_pfr']*100:.1f}%")

    delta = aware["bb_per_100_excl_monsters"] - unaware["bb_per_100_excl_monsters"]
    print(f"\nOpponent-awareness delta: {delta:+.2f} bb/100")
    _print_paired_delta("Opponent-awareness", unaware, aware)


def run_dossier_realism_comparison(n_hands: int):
    """Item 8: does the opponent-aware rule's measured benefit survive when it
    has to work off a realistic, noisy, no-minimum-hands-gate in-session
    dossier estimate (backend/dossier.py) instead of the ground-truth
    archetype label used everywhere else in this file? Three-way, same seed
    so the only thing that varies is what the hero bot is told."""
    print(f"\n[1/3] {n_hands} hands, opponent-UNAWARE (baseline)...")
    t0 = time.time()
    unaware = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=False)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[2/3] {n_hands} hands, opponent-AWARE, GROUND-TRUTH archetype (ceiling)...")
    t0 = time.time()
    ceiling = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True, archetype_source="ground_truth")
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[3/3] {n_hands} hands, opponent-AWARE, DOSSIER estimate (realistic)...")
    t0 = time.time()
    realistic = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True, archetype_source="dossier")
    print(f"  done in {time.time()-t0:.1f}s")

    print("\n" + "=" * 60)
    print("DOSSIER REALISM TEST (all WITH real rake)")
    print("=" * 60)
    for label, r in (
        ("Opponent-unaware (baseline)", unaware),
        ("Opponent-aware, ground truth (ceiling)", ceiling),
        ("Opponent-aware, dossier estimate (realistic)", realistic),
    ):
        print(f"\n{label}:")
        print(f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})")
        print(f"  monster pots: {r['monster_pot_rate']*100:.2f}%   hero VPIP/PFR: {r['hero_vpip']*100:.1f}%/{r['hero_pfr']*100:.1f}%")

    ceiling_gain = ceiling["bb_per_100_excl_monsters"] - unaware["bb_per_100_excl_monsters"]
    realistic_gain = realistic["bb_per_100_excl_monsters"] - unaware["bb_per_100_excl_monsters"]
    retained = (realistic_gain / ceiling_gain * 100) if ceiling_gain else 0.0
    print(f"\nCeiling gain (ground truth):     {ceiling_gain:+.2f} bb/100")
    print(f"Realistic gain (dossier estimate): {realistic_gain:+.2f} bb/100")
    print(f"Retained: {retained:.0f}% of the ceiling gain")
    _print_paired_delta("Ground-truth vs unaware", unaware, ceiling)
    _print_paired_delta("Dossier vs unaware", unaware, realistic)


def run_value_raise_comparison(n_hands: int):
    """v22 A/B test: does VALUE_RAISE_FACING_BET (raise, not just call, with
    two-pair-or-better facing a postflop bet -- see abc_bot.py's changelog)
    actually help, or does it just inflate variance/monster pots for no real
    gain? Both runs use real rake and ground-truth archetypes, same seed --
    the flag is the only thing that varies."""
    print(f"\n[1/2] {n_hands} hands, VALUE_RAISE_FACING_BET=False (pre-v22 baseline, call-only)...")
    abc_bot.VALUE_RAISE_FACING_BET = False
    t0 = time.time()
    baseline = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[2/2] {n_hands} hands, VALUE_RAISE_FACING_BET=True (v22)...")
    abc_bot.VALUE_RAISE_FACING_BET = True
    t0 = time.time()
    with_value_raise = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print("\n" + "=" * 60)
    print("VALUE-RAISE-FACING-A-BET A/B TEST (both WITH real rake)")
    print("=" * 60)
    for label, r in (("Baseline (call-only facing a bet)", baseline), ("v22 (value-raise two-pair+)", with_value_raise)):
        print(f"\n{label}:")
        print(f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})")
        print(f"  monster pots: {r['monster_pot_rate']*100:.2f}%   hero VPIP/PFR: {r['hero_vpip']*100:.1f}%/{r['hero_pfr']*100:.1f}%")

    delta = with_value_raise["bb_per_100_excl_monsters"] - baseline["bb_per_100_excl_monsters"]
    print(f"\nValue-raise delta: {delta:+.2f} bb/100")
    _print_paired_delta("Value-raise", baseline, with_value_raise)


def run_value_raise_tier_comparison(n_hands: int):
    """2026-08-11 follow-up to v22 (-9.66 bb/100 for raising two-pair-or-
    better facing a bet): was that driven by the whole tier, or specifically
    by the weaker end of it (plain two pair, which loses to a lot of what
    calls a raise)? Three arms, same seed: never raise (baseline), raise
    two-pair-or-better (v22, known), raise ONLY trips-or-better (excludes
    plain two pair -- see has_trips_or_better)."""
    print(f"\n[1/3] {n_hands} hands, call-only baseline...")
    abc_bot.VALUE_RAISE_FACING_BET = False
    abc_bot.VALUE_RAISE_TRIPS_OR_BETTER_ONLY = False
    t0 = time.time()
    baseline = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[2/3] {n_hands} hands, raise two-pair-or-better (v22)...")
    abc_bot.VALUE_RAISE_FACING_BET = True
    abc_bot.VALUE_RAISE_TRIPS_OR_BETTER_ONLY = False
    t0 = time.time()
    two_pair_plus = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[3/3] {n_hands} hands, raise trips-or-better ONLY...")
    abc_bot.VALUE_RAISE_FACING_BET = True
    abc_bot.VALUE_RAISE_TRIPS_OR_BETTER_ONLY = True
    t0 = time.time()
    trips_plus = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")
    abc_bot.VALUE_RAISE_TRIPS_OR_BETTER_ONLY = False  # reset module state

    print("\n" + "=" * 60)
    print("VALUE-RAISE TIER A/B TEST (all WITH real rake)")
    print("=" * 60)
    for label, r in (
        ("Baseline (call-only)", baseline),
        ("Raise two-pair-or-better (v22)", two_pair_plus),
        ("Raise trips-or-better ONLY", trips_plus),
    ):
        print(f"\n{label}:")
        print(f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})")
        print(f"  monster pots: {r['monster_pot_rate']*100:.2f}%   hero VPIP/PFR: {r['hero_vpip']*100:.1f}%/{r['hero_pfr']*100:.1f}%")

    print(f"\nDelta (two-pair+ vs baseline):  {two_pair_plus['bb_per_100_excl_monsters']-baseline['bb_per_100_excl_monsters']:+.2f} bb/100")
    print(f"Delta (trips+ only vs baseline): {trips_plus['bb_per_100_excl_monsters']-baseline['bb_per_100_excl_monsters']:+.2f} bb/100")
    _print_paired_delta("Two-pair+ vs baseline", baseline, two_pair_plus)
    _print_paired_delta("Trips+ only vs baseline", baseline, trips_plus)


def run_overbet_fold_comparison(n_hands: int):
    """v23 A/B test: does folding a plain top-pair-tier `made` hand to a
    bet bigger than the pot (FOLD_TOP_PAIR_VS_OVERBET, abc_bot.py) actually
    help, or does giving up live pots on a size-only signal cost more than
    it saves? Both runs use real rake and ground-truth archetypes, same
    seed -- the flag is the only thing that varies."""
    print(f"\n[1/2] {n_hands} hands, FOLD_TOP_PAIR_VS_OVERBET=False (baseline, always call with made)...")
    abc_bot.FOLD_TOP_PAIR_VS_OVERBET = False
    t0 = time.time()
    baseline = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[2/2] {n_hands} hands, FOLD_TOP_PAIR_VS_OVERBET=True (v23, fold top pair to a >pot-sized bet)...")
    abc_bot.FOLD_TOP_PAIR_VS_OVERBET = True
    t0 = time.time()
    with_fold = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")
    abc_bot.FOLD_TOP_PAIR_VS_OVERBET = False  # reset module state

    print("\n" + "=" * 60)
    print("FOLD-TOP-PAIR-VS-OVERBET A/B TEST (both WITH real rake)")
    print("=" * 60)
    for label, r in (("Baseline (always call with made)", baseline), ("v23 (fold top pair to overbet)", with_fold)):
        print(f"\n{label}:")
        print(f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})")
        print(f"  monster pots: {r['monster_pot_rate']*100:.2f}%   hero VPIP/PFR: {r['hero_vpip']*100:.1f}%/{r['hero_pfr']*100:.1f}%")

    delta = with_fold["bb_per_100_excl_monsters"] - baseline["bb_per_100_excl_monsters"]
    print(f"\nOverbet-fold delta: {delta:+.2f} bb/100")
    _print_paired_delta("Overbet-fold", baseline, with_fold)


def run_sizing_theory_comparison(n_hands: int):
    """v23 A/B test, sourced from published exploitative-sizing theory (see
    abc_bot.py's SIZE_UP_WITH_VERY_STRONG_HAND / SIZE_UP_ON_WET_BOARD
    comments): size value bets bigger with two-pair-or-better, and bigger on
    a wet/drawy board -- both untested until now, both independently
    toggled to isolate which (if either) actually helps. 4 arms, same seed:
    baseline (flat sizing), strength-only, wet-board-only, both combined."""
    print(f"\n[1/4] {n_hands} hands, baseline (flat sizing)...")
    abc_bot.SIZE_UP_WITH_VERY_STRONG_HAND = False
    abc_bot.SIZE_UP_ON_WET_BOARD = False
    t0 = time.time()
    baseline = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[2/4] {n_hands} hands, size up with very-strong-hand only...")
    abc_bot.SIZE_UP_WITH_VERY_STRONG_HAND = True
    abc_bot.SIZE_UP_ON_WET_BOARD = False
    t0 = time.time()
    strength_only = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[3/4] {n_hands} hands, size up on wet board only...")
    abc_bot.SIZE_UP_WITH_VERY_STRONG_HAND = False
    abc_bot.SIZE_UP_ON_WET_BOARD = True
    t0 = time.time()
    wet_board_only = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[4/4] {n_hands} hands, both combined...")
    abc_bot.SIZE_UP_WITH_VERY_STRONG_HAND = True
    abc_bot.SIZE_UP_ON_WET_BOARD = True
    t0 = time.time()
    both = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")
    abc_bot.SIZE_UP_WITH_VERY_STRONG_HAND = False
    abc_bot.SIZE_UP_ON_WET_BOARD = False  # reset module state

    print("\n" + "=" * 60)
    print("SIZING-BY-CONTEXT THEORY A/B TEST (all WITH real rake)")
    print("=" * 60)
    for label, r in (
        ("Baseline (flat sizing)", baseline),
        ("Size up with very-strong-hand", strength_only),
        ("Size up on wet board", wet_board_only),
        ("Both combined", both),
    ):
        print(f"\n{label}:")
        print(f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})")
        print(f"  monster pots: {r['monster_pot_rate']*100:.2f}%   hero VPIP/PFR: {r['hero_vpip']*100:.1f}%/{r['hero_pfr']*100:.1f}%")

    for label, r in (("strength-only", strength_only), ("wet-board-only", wet_board_only), ("both", both)):
        print(f"Delta ({label} vs baseline): {r['bb_per_100_excl_monsters']-baseline['bb_per_100_excl_monsters']:+.2f} bb/100")
        _print_paired_delta(label, baseline, r)


def _sync_value_3bet(is_wide: bool) -> None:
    """USE_WIDE_VALUE_3BET isn't read directly by choose_abc_action -- VALUE_
    3BET is computed from it ONCE at module import time (`VALUE_3BET =
    VALUE_3BET_WIDE if USE_WIDE_VALUE_3BET else VALUE_3BET_TIGHT`), so
    toggling the USE_WIDE_VALUE_3BET name alone at runtime has no effect.
    Any A/B test that includes it must also re-sync VALUE_3BET by hand."""
    abc_bot.VALUE_3BET = abc_bot.VALUE_3BET_WIDE if is_wide else abc_bot.VALUE_3BET_TIGHT


# SIZING_TARGET_ARCHETYPES (v14, A2) isn't a boolean flag -- it's the actual
# archetype set choose_abc_action checks membership against ({"Nit", "TAG"}),
# with no separate on/off gate. Toggling it "off" for a baseline arm means
# an empty set (membership always False), not literal False (which would
# crash -- `in False` isn't iterable, see the traceback this constant fixes).
_NON_BOOLEAN_FLAG_ON_VALUES = {
    "SIZING_TARGET_ARCHETYPES": {"Nit", "TAG"},
    "BLUFF_3BET_TARGET_ARCHETYPES": {"Nit", "TAG", "LAG"},
    "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD": {"Nit", "TAG"},
    "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO": {"QQ", "AKs", "AKo"},
    "SHOVE_VS_3BET_PLUS_RANGE": {"AA", "KK"},
}
_NON_BOOLEAN_FLAG_OFF_VALUES = {
    "SIZING_TARGET_ARCHETYPES": set(),
    "BLUFF_3BET_TARGET_ARCHETYPES": set(),
    "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD": set(),
    "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO": set(),
    "SHOVE_VS_3BET_PLUS_RANGE": set(),
}


def run_flag_confirmation(flag_names: list[str], n_hands: int, label: str):
    """2026-08-11: generic re-confirmation for any flag(s) shipped True on
    theory/a "doesn't measurably hurt" call rather than a demonstrated with-
    rake win, all still active in the live bot right now:
      v9  USE_WIDE_VALUE_3BET       -1.57 bb/100 with rake at 80k, noise
      v14 STEAL_WIDER_VS_NIT +
          SIZING_TARGET_ARCHETYPES  +0.63 bb/100 with rake at 80k, noise
      v15 WIDER_3BET_VS_LOOSE +
          SIZE_UP_ON_TURN           -0.27 bb/100 with rake at 80k, clean null
      v16 ISO_RAISE_OVER_LIMPERS    +2.14 bb/100 with rake at 80k, inside CI
      v17 DONK_BLUFF_VS_TIGHT       +2.33 bb/100 with rake at 80k, inside CI
    None of these were ever re-tested at real statistical power the way
    SQUEEZE_WIDER_RANGE (v21) was -- this closes that gap. Sets every flag
    in flag_names to False for the baseline arm and True for the treatment
    arm (leaving every OTHER flag at its current shipped value, same
    same-seed-only-this-toggles discipline as every A/B test in this file),
    real rake, ground-truth archetypes."""
    original = {name: getattr(abc_bot, name) for name in flag_names}

    def _apply(value: bool) -> None:
        for name in flag_names:
            if name in _NON_BOOLEAN_FLAG_ON_VALUES:
                real_value = _NON_BOOLEAN_FLAG_ON_VALUES[name] if value else _NON_BOOLEAN_FLAG_OFF_VALUES[name]
            else:
                real_value = value
            setattr(abc_bot, name, real_value)
        if "USE_WIDE_VALUE_3BET" in flag_names:
            _sync_value_3bet(value)

    flags_str = "+".join(flag_names)
    print(f"\n[1/2] {n_hands} hands, {flags_str}=False (baseline)...")
    _apply(False)
    t0 = time.time()
    baseline = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[2/2] {n_hands} hands, {flags_str}=True...")
    _apply(True)
    t0 = time.time()
    treatment = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    for name, val in original.items():
        setattr(abc_bot, name, val)
    if "USE_WIDE_VALUE_3BET" in flag_names:
        _sync_value_3bet(original["USE_WIDE_VALUE_3BET"])

    print("\n" + "=" * 60)
    print(f"RE-CONFIRMATION: {label} ({flags_str}) (both WITH real rake)")
    print("=" * 60)
    for arm_label, r in (("Baseline (False)", baseline), ("Treatment (True)", treatment)):
        print(f"\n{arm_label}:")
        print(f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})")
        print(f"  monster pots: {r['monster_pot_rate']*100:.2f}%   hero VPIP/PFR: {r['hero_vpip']*100:.1f}%/{r['hero_pfr']*100:.1f}%")

    delta = treatment["bb_per_100_excl_monsters"] - baseline["bb_per_100_excl_monsters"]
    print(f"\n{label} delta: {delta:+.2f} bb/100")
    _print_paired_delta(label, baseline, treatment)


def run_bluff_3bet_comparison(n_hands: int):
    """v24 A/B test: does BLUFF_3BET_VS_TIGHT (3-bet a speculative hand
    instead of calling/folding, specifically against a known Nit/TAG/LAG
    raiser -- see abc_bot.py's changelog, sourced from published
    exploitative micro-stakes strategy) actually help, or does giving up
    the pot-odds-favorable call range for a bluff cost more than the extra
    folds are worth? Both runs use real rake and ground-truth archetypes,
    same seed -- the flag is the only thing that varies."""
    print(f"\n[1/2] {n_hands} hands, BLUFF_3BET_VS_TIGHT=False (baseline, call-or-fold)...")
    abc_bot.BLUFF_3BET_VS_TIGHT = False
    t0 = time.time()
    baseline = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[2/2] {n_hands} hands, BLUFF_3BET_VS_TIGHT=True (v24, bluff 3-bet vs known Nit/TAG/LAG)...")
    abc_bot.BLUFF_3BET_VS_TIGHT = True
    t0 = time.time()
    with_bluff_3bet = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42, opponent_aware=True)
    print(f"  done in {time.time()-t0:.1f}s")
    abc_bot.BLUFF_3BET_VS_TIGHT = False  # reset module state

    print("\n" + "=" * 60)
    print("BLUFF-3-BET-VS-TIGHT A/B TEST (both WITH real rake)")
    print("=" * 60)
    for label, r in (("Baseline (call-or-fold)", baseline), ("v24 (bluff 3-bet vs Nit/TAG/LAG)", with_bluff_3bet)):
        print(f"\n{label}:")
        print(f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})")
        print(f"  monster pots: {r['monster_pot_rate']*100:.2f}%   hero VPIP/PFR: {r['hero_vpip']*100:.1f}%/{r['hero_pfr']*100:.1f}%")

    delta = with_bluff_3bet["bb_per_100_excl_monsters"] - baseline["bb_per_100_excl_monsters"]
    print(f"\nBluff-3-bet delta: {delta:+.2f} bb/100")
    _print_paired_delta("Bluff-3bet", baseline, with_bluff_3bet)


PRESET_FLAG_GROUPS = {
    "v9-wide-3bet": (["USE_WIDE_VALUE_3BET"], "v9 USE_WIDE_VALUE_3BET"),
    "v14-steal-sizing": (["STEAL_WIDER_VS_NIT", "SIZING_TARGET_ARCHETYPES"], "v14 A1+A2"),
    "v15-loose-3bet-turn": (["WIDER_3BET_VS_LOOSE", "SIZE_UP_ON_TURN"], "v15 B1+B2"),
    "v16-iso-limpers": (["ISO_RAISE_OVER_LIMPERS"], "v16 C1"),
    "v17-donk-bluff": (["DONK_BLUFF_VS_TIGHT"], "v17 C2"),
    "v21-squeeze-wide": (["SQUEEZE_WIDER_RANGE"], "v21 squeeze wider range"),
    "v21-squeeze-size": (["SQUEEZE_SIZE_UP_PER_CALLER"], "v21 squeeze size up per caller"),
    "v21-squeeze-both": (["SQUEEZE_WIDER_RANGE", "SQUEEZE_SIZE_UP_PER_CALLER"], "v21 squeeze wider+size"),
    "v25-barrel-bluff": (["BARREL_BLUFF_VS_TIGHT"], "v25 barrel bluff"),
    "v26-fold-premium-extreme": (["FOLD_PREMIUM_VS_EXTREME_AGGRO"], "v26 fold premium vs extreme aggro"),
    "v27-river-overbet": (["RIVER_OVERBET_NUTS_VS_LOOSE"], "v27 river overbet nuts vs loose"),
    "v28-optimal-sizing": (["OPTIMAL_VALUE_SIZING_PER_ARCHETYPE"], "v28 optimal value sizing per archetype"),
    "v29-iso-wider-range": (["ISO_WIDER_RANGE_OVER_LIMPERS"], "v29 isolate limpers with a wider range"),
    "v30-size-scaled-call": (["SIZE_SCALED_CALL_RANGE"], "v30 size-scaled call range"),
}


def main():
    global COMMON_RANDOM
    args = sys.argv[1:]
    if "--common-random" in args:
        COMMON_RANDOM = True
        args = [a for a in args if a != "--common-random"]
    if "--barrel-bluff" in args:
        remaining = [a for a in args if a != "--barrel-bluff"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_flag_confirmation(["BARREL_BLUFF_VS_TIGHT"], n_hands, "v25 barrel bluff")
        return
    if "--fold-premium-extreme" in args:
        remaining = [a for a in args if a != "--fold-premium-extreme"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_flag_confirmation(["FOLD_PREMIUM_VS_EXTREME_AGGRO"], n_hands, "v26 fold premium vs extreme aggro")
        return
    if "--river-overbet" in args:
        remaining = [a for a in args if a != "--river-overbet"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_flag_confirmation(["RIVER_OVERBET_NUTS_VS_LOOSE"], n_hands, "v27 river overbet nuts vs loose")
        return
    if "--optimal-sizing" in args:
        remaining = [a for a in args if a != "--optimal-sizing"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_flag_confirmation(["OPTIMAL_VALUE_SIZING_PER_ARCHETYPE"], n_hands, "v28 optimal value sizing per archetype")
        return
    if "--iso-wider-range" in args:
        remaining = [a for a in args if a != "--iso-wider-range"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_flag_confirmation(["ISO_WIDER_RANGE_OVER_LIMPERS"], n_hands, "v29 isolate limpers with a wider range")
        return
    if "--size-scaled-call" in args:
        remaining = [a for a in args if a != "--size-scaled-call"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_flag_confirmation(["SIZE_SCALED_CALL_RANGE"], n_hands, "v30 size-scaled call range")
        return
    if "--flag-confirm" in args:
        idx = args.index("--flag-confirm")
        preset = args[idx + 1]
        remaining = args[idx + 2 :]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        if preset == "all":
            for key, (flag_names, label) in PRESET_FLAG_GROUPS.items():
                run_flag_confirmation(flag_names, n_hands, label)
        elif preset in PRESET_FLAG_GROUPS:
            flag_names, label = PRESET_FLAG_GROUPS[preset]
            run_flag_confirmation(flag_names, n_hands, label)
        else:
            print(f"Unknown preset '{preset}'. Options: all, {', '.join(PRESET_FLAG_GROUPS)}")
        return
    if "--bluff-3bet" in args:
        remaining = [a for a in args if a != "--bluff-3bet"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_bluff_3bet_comparison(n_hands)
        return
    if "--overbet-fold" in args:
        remaining = [a for a in args if a != "--overbet-fold"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_overbet_fold_comparison(n_hands)
        return
    if "--value-raise" in args:
        remaining = [a for a in args if a != "--value-raise"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_value_raise_comparison(n_hands)
        return
    if "--value-raise-tiers" in args:
        remaining = [a for a in args if a != "--value-raise-tiers"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_value_raise_tier_comparison(n_hands)
        return
    if "--sizing-theory" in args:
        remaining = [a for a in args if a != "--sizing-theory"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_sizing_theory_comparison(n_hands)
        return
    if "--dossier-realism" in args:
        remaining = [a for a in args if a != "--dossier-realism"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_dossier_realism_comparison(n_hands)
        return
    if "--opponent-aware" in args:
        remaining = [a for a in args if a != "--opponent-aware"]
        n_hands = int(remaining[0]) if remaining and remaining[0].isdigit() else 80000
        run_opponent_aware_comparison(n_hands)
        return

    n_hands = int(args[0]) if args and args[0].isdigit() else None

    if n_hands is None:
        print("[calibrating] timing 2,000 hands to size the full run...")
        t0 = time.time()
        calib = run_batch(2000, RAKE_PERCENT, RAKE_CAP_BB, seed=1)
        elapsed = time.time() - t0
        per_hand = elapsed / calib["hands"] if calib["hands"] else elapsed / 2000
        print(f"  {calib['hands']} hands in {elapsed:.1f}s -> {per_hand*1000:.2f}ms/hand")
        n_hands = 30000
        est = per_hand * n_hands
        print(f"  estimated time for {n_hands} hands: {est/60:.1f} min (will run this many, x2 for rake/no-rake)")

    print(f"\n[run 1/2] {n_hands} hands WITH real PokerDom rake (5%, cap 5bb, no flop no drop)...")
    t0 = time.time()
    with_rake = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[run 2/2] {n_hands} hands WITHOUT rake (matches how the guide's own EV numbers were computed)...")
    t0 = time.time()
    without_rake = run_batch(n_hands, 0.0, 0.0, seed=42)
    print(f"  done in {time.time()-t0:.1f}s")

    print("\n" + "=" * 60)
    print("RESULTS -- ABC bot (Tier 1 strategy only) at a 6-max table")
    print("=" * 60)
    for label, r in (("WITH rake (realistic)", with_rake), ("WITHOUT rake (guide's own basis)", without_rake)):
        print(f"\n{label}:")
        print(f"  hands played:      {r['hands']}")
        print(f"  net result:        {r['hero_net_bb']:+.2f}bb")
        print(f"  winrate:           {r['bb_per_100']:+.2f} bb/100  (95% CI +/- {r['bb_per_100_ci95']:.2f})")
        print(f"  median hand:       {r['median_hand_bb']:+.2f}bb   win-rate-by-hand: {r['win_hand_rate']*100:.1f}%")
        print(f"  monster pots >50bb: {r['monster_pot_rate']*100:.2f}% of hands")
        print(
            f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}"
            f"  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})"
        )
        print(f"  hero VPIP/PFR:     {r['hero_vpip']*100:.1f}% / {r['hero_pfr']*100:.1f}%")

    delta = without_rake["bb_per_100"] - with_rake["bb_per_100"]
    print(f"\nRake's cost to this strategy: ~{delta:.2f} bb/100")
    print(
        "\nCaveat: the ML bots' bet-sizing model has no stack-depth feature (documented\n"
        "limitation) and can escalate raise wars into pots far bigger than a realistic\n"
        "200bb-cap game -- see 'monster pots' rate above. These rare, huge pots dominate\n"
        "variance, which is why the 95% CI is reported alongside the mean rather than\n"
        "treating bb/100 as a precise number."
    )


if __name__ == "__main__":
    main()
