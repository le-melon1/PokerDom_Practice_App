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
"""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


def run_batch(
    n_hands: int, rake_percent: float, rake_cap_bb: float, seed: int,
    opponent_aware: bool = True, archetype_source: str = "ground_truth",
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

    hero_net_total = 0.0
    hero_net_per_hand: list[float] = []
    hero_net_per_hand_normal: list[float] = []  # excludes monster pots
    hero_vpip_hands = 0
    hero_pfr_hands = 0
    hands_completed = 0
    monster_pots = 0  # pots > 50bb -- flags hands where the ML bots' known
    # stack-unaware sizing model ran away with repeated large raises (see
    # scripts/simulate_abc_bot.py's usage docstring / final report)

    for _ in range(n_hands):
        if table.players[HERO_SEAT].stack <= 0:
            table.players[HERO_SEAT].stack = STARTING_STACK  # rebuy, keep sim running

        try:
            hand = table.start_new_hand()
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
                action, amount = choose_bot_action(hand, seat, archetype=archetype)
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
    }


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


def main():
    args = sys.argv[1:]
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
