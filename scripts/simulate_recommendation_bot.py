"""Does a bot that plays ONLY what the live EV panel recommends
(recommend_gto_action, backend/ev/live_ev.py -- the exact function behind
the practice app's "рекомендация" the human sees) actually win money?

Every other bot in this project (behavior_clone.py's ML population bots,
abc_bot.py's hand-coded strategy) has been measured this way via
scripts/simulate_abc_bot.py. The live EV panel's recommendation itself
never has -- it's been validated piece by piece (realistic fold/call/raise
MIXES on real decision samples, latency, the multiway equity fix) but never
end to end as "does following this policy actually make money."

Same self-play setup as simulate_abc_bot.py: 6-max, population-weighted
archetype mix, real session-length turnover, real PokerDom rake. Hero acts
via recommend_gto_action(..., dossier=state_dossier) -- auto mode, the same
dossier-blended read a real human using the app would get, not the
ground-truth-archetype ceiling test abc_bot.py's own harness uses.

Usage: python3 scripts/simulate_recommendation_bot.py [n_hands]
"""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.bots.behavior_clone import choose_bot_action
from backend.dossier import TableDossier
from backend.engine.hand import Hand, IllegalAction
from backend.engine.table import Table
from backend.ev.live_ev import recommend_gto_action
from backend.sessions.live_dynamics import TableTurnover

HERO_SEAT = 1
RAKE_PERCENT = 0.05
RAKE_CAP_BB = 5.0
STARTING_STACK = 200.0
MAX_SEATS = 6
EQUITY_TRIALS = 400  # lower than the live app's 800-1200 -- affordable at simulation scale, see changelog


def _apply_recommendation(hand: Hand, seat: int, rec) -> None:
    """Map a GTORecommendation onto a legal Hand.apply_action call. Defensive
    against edge cases the live panel never has to handle standalone (a
    recommended amount that's since become illegal because state moved on,
    a "call"/"check" mismatch) -- falls back to the closest legal action
    rather than crashing the simulation, same spirit as the UI's own
    IllegalAction handling in api.py."""
    legal = hand.legal_actions(seat)
    action, amount = rec.recommended_action, rec.recommended_amount

    if action == "fold":
        hand.apply_action(seat, "fold")
        return
    if action == "call":
        if legal["can_call"]:
            hand.apply_action(seat, "call")
        elif legal["can_check"]:
            hand.apply_action(seat, "check")
        else:
            hand.apply_action(seat, "fold")
        return
    if action == "check":
        if legal["can_check"]:
            hand.apply_action(seat, "check")
        elif legal["can_call"]:
            hand.apply_action(seat, "call")
        else:
            hand.apply_action(seat, "fold")
        return
    if action in ("bet", "raise"):
        min_to = legal["min_raise_to"] if hand.current_bet > 0 else hand.big_blind
        max_to = legal["max_raise_to"]
        if max_to < min_to - 1e-9:
            # Can't even min-raise (covered already) -- closest legal action is call/check.
            if legal["can_call"]:
                hand.apply_action(seat, "call")
            elif legal["can_check"]:
                hand.apply_action(seat, "check")
            else:
                hand.apply_action(seat, "fold")
            return
        clamped = max(min_to, min(amount if amount is not None else min_to, max_to))
        try:
            hand.apply_action(seat, action, clamped)
        except IllegalAction:
            if legal["can_call"]:
                hand.apply_action(seat, "call")
            else:
                hand.apply_action(seat, "check")
        return
    # Unknown label -- shouldn't happen, but never crash the sim over it.
    if legal["can_check"]:
        hand.apply_action(seat, "check")
    elif legal["can_call"]:
        hand.apply_action(seat, "call")
    else:
        hand.apply_action(seat, "fold")


def run_batch(n_hands: int, rake_percent: float, rake_cap_bb: float, seed: int) -> dict:
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=MAX_SEATS, rake_percent=rake_percent, rake_cap_bb=rake_cap_bb)
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    turnover = TableTurnover(bot_seats, rng_seed=seed)
    dossier = TableDossier()
    for seat in bot_seats:
        dossier.reset_seat(seat)
    for seat in range(1, MAX_SEATS + 1):
        table.add_player(seat=seat, name=("Hero" if seat == HERO_SEAT else f"Bot{seat}"), stack=STARTING_STACK)

    hero_net_total = 0.0
    hero_net_per_hand: list[float] = []
    hero_net_per_hand_normal: list[float] = []
    hero_vpip_hands = 0
    hero_pfr_hands = 0
    hands_completed = 0
    monster_pots = 0

    for i in range(n_hands):
        if table.players[HERO_SEAT].stack <= 0:
            table.players[HERO_SEAT].stack = STARTING_STACK

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
                rec = recommend_gto_action(hand, HERO_SEAT, opponent_archetype=None, dossier=dossier, equity_trials=EQUITY_TRIALS)
                try:
                    _apply_recommendation(hand, seat, rec)
                except IllegalAction:
                    hand.apply_action(seat, "fold")
            else:
                archetype = turnover.archetype_for(seat)
                freq_tier = turnover.freq_tier_for(seat)
                action, amount = choose_bot_action(hand, seat, archetype=archetype, freq_tier=freq_tier)
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
                dossier.reset_seat(seat)

        if (i + 1) % 200 == 0:
            print(f"  ... {i + 1}/{n_hands} hands ({hands_completed} completed)", flush=True)

    n = hands_completed
    mean = hero_net_total / n if n else 0.0
    stdev = statistics.pstdev(hero_net_per_hand) if n > 1 else 0.0
    sem = stdev / (n ** 0.5) if n else 0.0
    ci95_bb100 = 1.96 * sem * 100
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
        "win_hand_rate": win_hand_rate,
        "monster_pot_rate": monster_pots / n if n else 0.0,
        "bb_per_100_excl_monsters": mean_normal * 100,
        "bb_per_100_excl_monsters_ci95": ci95_normal,
        "hero_vpip": hero_vpip_hands / n if n else 0.0,
        "hero_pfr": hero_pfr_hands / n if n else 0.0,
    }


def _print_result(label: str, r: dict) -> None:
    # Printed immediately after each arm finishes, not batched to the end --
    # a killed/interrupted run (real risk on a shared, resource-constrained
    # machine) still leaves whatever arms DID finish actually readable in
    # the captured output instead of silently lost (a real incident: the
    # first "WITH rake" arm here once fully completed in 3606s but the
    # result was never printed because the process got killed partway
    # through the second arm, before the old end-of-script print block ran).
    print(f"\n{label}:")
    print(f"  hands played:      {r['hands']}")
    print(f"  net result:        {r['hero_net_bb']:+.2f}bb")
    print(f"  winrate:           {r['bb_per_100']:+.2f} bb/100  (95% CI +/- {r['bb_per_100_ci95']:.2f})")
    print(f"  monster pots >50bb: {r['monster_pot_rate']*100:.2f}% of hands")
    print(
        f"  bb/100 excl. monster pots: {r['bb_per_100_excl_monsters']:+.2f}"
        f"  (95% CI +/- {r['bb_per_100_excl_monsters_ci95']:.2f})"
    )
    print(f"  hero VPIP/PFR:     {r['hero_vpip']*100:.1f}% / {r['hero_pfr']*100:.1f}%")


def main():
    n_hands = int(sys.argv[1]) if len(sys.argv) > 1 else 2000

    print("=" * 60)
    print("RESULTS -- a bot that plays ONLY the live EV panel's recommendation")
    print("=" * 60)

    print(f"\n[run 1/2] {n_hands} hands WITH real PokerDom rake...")
    t0 = time.time()
    with_rake = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42)
    print(f"  done in {time.time()-t0:.1f}s")
    _print_result("WITH rake (realistic)", with_rake)

    print(f"\n[run 2/2] {n_hands} hands WITHOUT rake...")
    t0 = time.time()
    without_rake = run_batch(n_hands, 0.0, 0.0, seed=42)
    print(f"  done in {time.time()-t0:.1f}s")
    _print_result("WITHOUT rake", without_rake)


if __name__ == "__main__":
    main()
