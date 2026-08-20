"""2026-08-10: measured recommend_gto_action's actual fold/call/raise mix
on real postflop MULTIWAY (2+ live opponents) facing-bet decisions, while
briefly generalizing _abc_strategy_action (backend/ev/live_ev.py) from
preflop-only to also cover postflop multiway.

RESULT / WHY IT WAS REVERTED: 324 decisions over 3000 hands gave call
69.1% / fold 30.9% / raise 0.0%. abc_bot.py's postflop-facing-a-bet rule
is intentionally call-or-fold only ("Never raise postflop", see its own
docstring) -- a disclosed simplification of that bot, not a bug. Routing
multiway postflop through it doesn't fix "recommends call too often," it
makes that complaint worse (raise disappears entirely). Reverted; see
_abc_strategy_action's docstring in live_ev.py for the full writeup.
Multiway postflop facing-bet stays on the fold-equity-corrected
wizard_like heuristic (73.1% raise on the same style of sample --
imperfect but at least offers a real mix of all three actions).

Kept for the record, same as scripts/diagnose_monster_pots.py's role for
the monster-pot investigation. Same self-play setup: hero actually plays
via choose_abc_action (so hands progress realistically), bots via
choose_bot_action. At every hero postflop decision node facing a bet with
2+ live opponents, recommend_gto_action is called separately (its result
is NOT used to play the hand, only tallied) to measure what the live EV
panel would have told a human player in that exact spot.

Usage: python3 scripts/diagnose_postflop_multiway_recommendation.py [n_hands]
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.bots.abc_bot import choose_abc_action
from backend.bots.behavior_clone import choose_bot_action
from backend.dossier import TableDossier
from backend.engine.hand import IllegalAction
from backend.engine.table import Table
from backend.ev.live_ev import recommend_gto_action
from backend.sessions.live_dynamics import TableTurnover

HERO_SEAT = 1
STARTING_STACK = 200.0
MAX_SEATS = 6


def main():
    n_hands = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=MAX_SEATS, rake_percent=0.0, rake_cap_bb=0.0)
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    turnover = TableTurnover(bot_seats, rng_seed=42)
    dossier = TableDossier()
    for seat in bot_seats:
        dossier.reset_seat(seat)
    for seat in range(1, MAX_SEATS + 1):
        table.add_player(seat=seat, name=("Hero" if seat == HERO_SEAT else f"Bot{seat}"), stack=STARTING_STACK)

    tally: dict[str, int] = {}
    n_decisions = 0
    hands_completed = 0
    start = time.monotonic()

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
                legal = hand.legal_actions(seat)
                live_opponents = [p for p in hand.players.values() if p.in_hand and p.seat != seat]
                if hand.street != "preflop" and legal["can_call"] and legal["call_amount"] > 0 and len(live_opponents) >= 2:
                    rec = recommend_gto_action(hand, seat, opponent_archetype=None, dossier=dossier, equity_trials=400)
                    tally[rec.recommended_action] = tally.get(rec.recommended_action, 0) + 1
                    n_decisions += 1
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

        dossier.record_hand(hand)
        seat_stacks = {seat: p.stack for seat, p in hand.players.items() if seat != HERO_SEAT}
        turned_over = turnover.after_hand(seat_stacks, STARTING_STACK)
        for seat, did_turn_over in turned_over.items():
            if did_turn_over:
                table.players[seat].stack = STARTING_STACK
                table.players[seat].sitting_out = False
                dossier.reset_seat(seat)

    elapsed = time.monotonic() - start
    print(f"checked {n_decisions} POSTFLOP MULTIWAY (2+ opponents) hero facing-bet decisions "
          f"(ABC-strategy source, {hands_completed} hands) in {elapsed:.1f}s")
    print(tally)
    for action, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {action}: {count / n_decisions:.1%}")


if __name__ == "__main__":
    main()
