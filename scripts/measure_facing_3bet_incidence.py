"""2026-08-13: measures the TRUE natural incidence (no card/action forcing)
of hero facing a preflop re-raise (n_raises>=2) at all, and specifically
while holding a premium hand (AA/KK or the broader PREMIUM_VS_3BET set) --
needed to correctly rescale the --force-opponent-reraise + --hero-hand-
filter results for r13/v26/r15v-fold-*/r18v-shove-* (see CLAUDE.md's
"r13/v26/..." section: those tools inflate this spot's frequency by
roughly 1000x, and the reported bb/100 needs dividing by (forced_incidence
/ true_incidence) to mean anything as a population contribution).

Usage: python3 scripts/measure_facing_3bet_incidence.py [n_hands]
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.bots.abc_bot import PREMIUM_VS_3BET, choose_abc_action, _hand_notation
from backend.bots.behavior_clone import choose_bot_action
from backend.engine.hand import IllegalAction
from backend.engine.table import Table
from backend.sessions.live_dynamics import TableTurnover

HERO_SEAT = 1
STARTING_STACK = 200.0
MAX_SEATS = 6


def main():
    n_hands = int(sys.argv[1]) if len(sys.argv) > 1 else 200000
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=MAX_SEATS, rake_percent=0.05, rake_cap_bb=5.0)
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    turnover = TableTurnover(bot_seats, rng_seed=42)

    facing_2plus_raises = 0
    facing_2plus_with_premium = 0
    facing_2plus_with_aa_kk = 0
    hands_completed = 0
    t0 = time.monotonic()

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
            if seat == HERO_SEAT and hand.street == "preflop":
                n_raises = sum(1 for a in hand.actions if a.street == "preflop" and a.action == "raises")
                if n_raises >= 2:
                    facing_2plus_raises += 1
                    notation = _hand_notation(hand.players[HERO_SEAT].hole_cards)
                    if notation in PREMIUM_VS_3BET:
                        facing_2plus_with_premium += 1
                    if notation in ("AA", "KK"):
                        facing_2plus_with_aa_kk += 1
                opponent_archetypes = {s: turnover.archetype_for(s) for s in bot_seats if hand.players[s].in_hand}
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

        seat_stacks = {seat: p.stack for seat, p in hand.players.items() if seat != HERO_SEAT}
        turned_over = turnover.after_hand(seat_stacks, STARTING_STACK)
        for seat, did_turn_over in turned_over.items():
            if did_turn_over:
                table.players[seat].stack = STARTING_STACK
                table.players[seat].sitting_out = False

        if (i + 1) % 20000 == 0:
            elapsed = time.monotonic() - t0
            print(
                f"  ... {i + 1}/{n_hands} hands, facing_2plus_raises={facing_2plus_raises} "
                f"({facing_2plus_raises / hands_completed * 100:.4f}%), "
                f"with_premium={facing_2plus_with_premium}, with_AA_KK={facing_2plus_with_aa_kk}, "
                f"elapsed={elapsed:.0f}s",
                flush=True,
            )

    elapsed = time.monotonic() - t0
    print(f"\nfinished: {hands_completed} hands completed in {elapsed:.0f}s")
    print(f"facing n_raises>=2 (any hand): {facing_2plus_raises} ({facing_2plus_raises / hands_completed * 100:.4f}% of hands)")
    print(f"facing n_raises>=2 WITH premium (PREMIUM_VS_3BET): {facing_2plus_with_premium} ({facing_2plus_with_premium / hands_completed * 100:.5f}% of hands)")
    print(f"facing n_raises>=2 WITH AA/KK specifically: {facing_2plus_with_aa_kk} ({facing_2plus_with_aa_kk / hands_completed * 100:.5f}% of hands)")


if __name__ == "__main__":
    main()
