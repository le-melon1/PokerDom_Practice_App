"""Heads-up variant of simulate_recommendation_bot.py, built to isolate the
CFR postflop solver's real quality specifically. _solve_live_postflop_subgame
(backend/ev/live_ev.py) only ever fires when there's exactly ONE live
opponent -- in the 6-max version, most postflop decisions are multiway and
fall back to the wizard_like heuristic instead, diluting any measurement of
"how good is the solver" with "how good is the heuristic." Forcing MAX_SEATS
to 2 makes every postflop hero decision heads-up, so every one of them goes
through the real solver, not the heuristic (preflop still comes from the
ABC-strategy override either way, same as the 6-max version).

Opponent seat still turns over through the population-weighted archetype mix
via TableTurnover, same as every other simulate_*.py script -- "against
players," not against one fixed static bot.

Usage: python3 scripts/simulate_recommendation_bot_headsup.py [n_hands]
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
from scripts.simulate_recommendation_bot import _apply_recommendation

HERO_SEAT = 1
OPPONENT_SEAT = 2
RAKE_PERCENT = 0.05
RAKE_CAP_BB = 5.0
STARTING_STACK = 200.0
MAX_SEATS = 2
EQUITY_TRIALS = 400


def run_batch(n_hands: int, rake_percent: float, rake_cap_bb: float, seed: int) -> dict:
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=MAX_SEATS, rake_percent=rake_percent, rake_cap_bb=rake_cap_bb)
    turnover = TableTurnover([OPPONENT_SEAT], rng_seed=seed)
    dossier = TableDossier()
    dossier.reset_seat(OPPONENT_SEAT)
    for seat in range(1, MAX_SEATS + 1):
        table.add_player(seat=seat, name=("Hero" if seat == HERO_SEAT else "Bot2"), stack=STARTING_STACK)

    hero_net_total = 0.0
    hero_net_per_hand: list[float] = []
    hero_net_per_hand_normal: list[float] = []
    hero_vpip_hands = 0
    hero_pfr_hands = 0
    n_solver_decisions = 0
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
                if hand.street != "preflop" and rec.gto_equilibrium and rec.gto_equilibrium.get("flop_subgame"):
                    n_solver_decisions += 1
                try:
                    _apply_recommendation(hand, seat, rec)
                except IllegalAction:
                    hand.apply_action(seat, "fold")
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
        seat_stacks = {OPPONENT_SEAT: hand.players[OPPONENT_SEAT].stack}
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

    n_normal = len(hero_net_per_hand_normal)
    mean_normal = (sum(hero_net_per_hand_normal) / n_normal) if n_normal else 0.0
    stdev_normal = statistics.pstdev(hero_net_per_hand_normal) if n_normal > 1 else 0.0
    ci95_normal = 1.96 * (stdev_normal / (n_normal ** 0.5)) * 100 if n_normal else 0.0

    return {
        "hands": n,
        "hero_net_bb": hero_net_total,
        "bb_per_100": mean * 100,
        "bb_per_100_ci95": ci95_bb100,
        "monster_pot_rate": monster_pots / n if n else 0.0,
        "bb_per_100_excl_monsters": mean_normal * 100,
        "bb_per_100_excl_monsters_ci95": ci95_normal,
        "hero_vpip": hero_vpip_hands / n if n else 0.0,
        "hero_pfr": hero_pfr_hands / n if n else 0.0,
        "n_solver_decisions": n_solver_decisions,
    }


def main():
    n_hands = int(sys.argv[1]) if len(sys.argv) > 1 else 1500

    print(f"[run 1/2] {n_hands} heads-up hands WITH real PokerDom rake...")
    t0 = time.time()
    with_rake = run_batch(n_hands, RAKE_PERCENT, RAKE_CAP_BB, seed=42)
    print(f"  done in {time.time()-t0:.1f}s")

    print(f"\n[run 2/2] {n_hands} heads-up hands WITHOUT rake...")
    t0 = time.time()
    without_rake = run_batch(n_hands, 0.0, 0.0, seed=42)
    print(f"  done in {time.time()-t0:.1f}s")

    print("\n" + "=" * 60)
    print("RESULTS -- heads-up, isolates the CFR postflop solver specifically")
    print("=" * 60)
    for label, r in (("WITH rake (realistic)", with_rake), ("WITHOUT rake", without_rake)):
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
        print(f"  postflop decisions where the CFR solver fired: {r['n_solver_decisions']}")


if __name__ == "__main__":
    main()
