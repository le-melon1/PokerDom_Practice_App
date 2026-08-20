"""Classifies the mechanism behind monster pots (>50bb) that survive the
2026-08-07 behavior_clone.py fix (raise-suppression + progressive pot
damping) and the abc_bot.py HERO_PROGRESSIVE_POT_DAMPING follow-up. Those
fixes targeted raise wars specifically (Hand.min_raise flooring damped raise
amounts back up). Open question: is the remaining ~20% still raise-war-driven
(the damping/suppression thresholds just weren't tight enough), or is it a
DIFFERENT mechanism -- a multiway pot inflated by one bet plus several calls,
no raise at all, just N players putting money in on every street?

Same table/opponent setup as scripts/simulate_abc_bot.py, run without a
rake distinction (mechanism doesn't depend on rake).

Usage: python3 scripts/diagnose_monster_pots.py [n_hands]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.bots.abc_bot import choose_abc_action
from backend.bots.behavior_clone import choose_bot_action
from backend.dossier import TableDossier
from backend.engine.hand import IllegalAction
from backend.engine.table import Table
from backend.sessions.live_dynamics import TableTurnover

HERO_SEAT = 1
STARTING_STACK = 200.0
MAX_SEATS = 6


def classify(hand) -> str:
    max_raises_on_a_street = 0
    by_street: dict[str, int] = {}
    for a in hand.actions:
        if a.action == "raises":
            by_street[a.street] = by_street.get(a.street, 0) + 1
    if by_street:
        max_raises_on_a_street = max(by_street.values())

    n_callers = sum(1 for a in hand.actions if a.action == "calls")

    if max_raises_on_a_street >= 3:
        return "raise_war (3+ raises one street)"
    if max_raises_on_a_street >= 1:
        return "moderate_raising (1-2 raises/street, still escalated)"
    if n_callers >= 4:
        return "multiway_calling (bet + 3+ calls, no raise)"
    return "other"


def main():
    n_hands = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=MAX_SEATS, rake_percent=0.0, rake_cap_bb=0.0)
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    turnover = TableTurnover(bot_seats, rng_seed=42)
    dossier = TableDossier()
    for seat in bot_seats:
        dossier.reset_seat(seat)
    for seat in range(1, MAX_SEATS + 1):
        table.add_player(seat=seat, name=("Hero" if seat == HERO_SEAT else f"Bot{seat}"), stack=STARTING_STACK)

    monster_count = 0
    categories: dict[str, int] = {}
    hands_completed = 0

    for _ in range(n_hands):
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
                opponent_archetypes = {s: turnover.archetype_for(s) for s in bot_seats if hand.players[s].in_hand}
                action, amount = choose_abc_action(hand, seat, opponent_archetypes=opponent_archetypes)
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

        pot = sum(p.total_contributed for p in hand.players.values())
        if pot > 50:
            monster_count += 1
            cat = classify(hand)
            categories[cat] = categories.get(cat, 0) + 1

        dossier.record_hand(hand)
        seat_stacks = {seat: p.stack for seat, p in hand.players.items() if seat != HERO_SEAT}
        turned_over = turnover.after_hand(seat_stacks, STARTING_STACK)
        for seat, did_turn_over in turned_over.items():
            if did_turn_over:
                table.players[seat].stack = STARTING_STACK
                table.players[seat].sitting_out = False
                dossier.reset_seat(seat)

    print(f"hands completed: {hands_completed}")
    print(f"monster pots (>50bb): {monster_count} ({monster_count / hands_completed:.2%})")
    print("\nmechanism breakdown:")
    for cat, n in sorted(categories.items(), key=lambda kv: -kv[1]):
        print(f"  {cat}: {n} ({n / monster_count:.1%} of monster pots)")


if __name__ == "__main__":
    main()
