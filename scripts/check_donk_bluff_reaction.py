"""Empirically verify the claim made to the user: since behavior_clone.py's
ML bots have no opponent-history features at all (CAT_FEATURES = street/
position/archetype only), hero's repeated donk-bluffing (v17,
DONK_BLUFF_VS_TIGHT) should show ZERO drift in opponent fold% over the
course of a long session -- they can't learn to distrust it, by
construction. This runs the same simulation as simulate_abc_bot.py but logs
every donk-bluff event (hand index + opponent response) to check that claim
against real simulated data rather than just trusting the code-reading
argument.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.bots.abc_bot import (
    TIGHT_ARCHETYPES_FOR_DONK_BLUFF,
    _had_preflop_initiative,
    _live_opponent_seats,
    _n_bets_or_raises_this_street,
    choose_abc_action,
    has_top_pair_or_better,
)
from backend.bots.behavior_clone import choose_bot_action
from backend.dossier import TableDossier
from backend.engine.hand import IllegalAction
from backend.engine.table import Table
from backend.sessions.live_dynamics import TableTurnover

HERO_SEAT = 1
MAX_SEATS = 6
STARTING_STACK = 200.0


def is_donk_bluff_spot(hand, seat, opponent_archetypes) -> bool:
    """Recreate the exact v17 trigger condition post-hoc, to identify which
    of hero's bets were donk bluffs, without needing choose_abc_action to
    expose its internal branch."""
    if hand.street == "preflop":
        return False
    legal = hand.legal_actions(seat)
    if legal["call_amount"] > 0:
        return False
    if _n_bets_or_raises_this_street(hand) != 0:
        return False
    if _had_preflop_initiative(hand, seat):
        return False
    player = hand.players[seat]
    if has_top_pair_or_better(player.hole_cards, hand.board):
        return False  # a value bet, not a bluff
    live_opponents = _live_opponent_seats(hand, seat)
    if len(live_opponents) != 1:
        return False
    return opponent_archetypes.get(live_opponents[0]) in TIGHT_ARCHETYPES_FOR_DONK_BLUFF


def main(n_hands: int = 80000, seed: int = 42):
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=MAX_SEATS, rake_percent=0.05, rake_cap_bb=5.0)
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    turnover = TableTurnover(bot_seats, rng_seed=seed)
    dossier = TableDossier()
    for seat in bot_seats:
        dossier.reset_seat(seat)
    for seat in range(1, MAX_SEATS + 1):
        table.add_player(seat=seat, name=("Hero" if seat == HERO_SEAT else f"Bot{seat}"), stack=STARTING_STACK)

    events = []  # (hand_index, opponent_seat, opponent_archetype, response)
    hands_completed = 0

    for hand_index in range(n_hands):
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

        # pending donk-bluff bets in THIS hand, resolved once the hand (and
        # therefore the opponent's response) is fully played out -- checking
        # in the same while-loop iteration as hero's bet was a bug: the
        # opponent hasn't acted yet at that point, so the response lookup
        # always found nothing.
        pending_donk_bets = []  # (opp_seat, opp_archetype, street, n_actions_before)

        guard = 0
        while not hand.finished and guard < 500:
            seat = hand.current_actor()
            if seat is None:
                break
            if seat == HERO_SEAT:
                opponent_archetypes = {s: turnover.archetype_for(s) for s in bot_seats if hand.players[s].in_hand}
                donk_spot = is_donk_bluff_spot(hand, seat, opponent_archetypes)
                if donk_spot:
                    opp_seat = _live_opponent_seats(hand, seat)[0]
                    opp_archetype = opponent_archetypes[opp_seat]
                    street_at_bet = hand.street
                    n_actions_before = len(hand.actions)
                action, amount = choose_abc_action(hand, seat, opponent_archetypes=opponent_archetypes)
            else:
                archetype = turnover.archetype_for(seat)
                action, amount = choose_bot_action(hand, seat, archetype=archetype)
            try:
                hand.apply_action(seat, action, amount)
            except IllegalAction:
                hand.apply_action(seat, "fold")
            guard += 1

            if seat == HERO_SEAT and donk_spot:
                pending_donk_bets.append((opp_seat, opp_archetype, street_at_bet, n_actions_before))

        if not hand.finished:
            continue
        hands_completed += 1

        for opp_seat, opp_archetype, street_at_bet, n_actions_before in pending_donk_bets:
            resp = next(
                (a for a in hand.actions[n_actions_before:] if a.seat == opp_seat and a.street == street_at_bet),
                None,
            )
            if resp is not None:
                events.append((hand_index, opp_seat, opp_archetype, resp.action))

        dossier.record_hand(hand)
        seat_stacks = {seat: p.stack for seat, p in hand.players.items() if seat != HERO_SEAT}
        turned_over = turnover.after_hand(seat_stacks, STARTING_STACK)
        for seat, did_turn_over in turned_over.items():
            if did_turn_over:
                table.players[seat].stack = STARTING_STACK
                table.players[seat].sitting_out = False
                dossier.reset_seat(seat)

    print(f"hands completed: {hands_completed}")
    print(f"donk-bluff events captured: {len(events)}")

    if not events:
        print("no events captured -- check trigger logic")
        return

    n = len(events)
    deciles = [[] for _ in range(10)]
    for i, (hand_index, opp_seat, opp_archetype, response) in enumerate(events):
        decile = min(9, i * 10 // n)
        deciles[decile].append(response)

    print("\nfold% to donk bluff, by decile of OCCURRENCE ORDER (not hand index -- order among the events themselves):")
    for i, d in enumerate(deciles):
        if not d:
            continue
        fold_pct = sum(1 for r in d if r == "folds") / len(d)
        print(f"  decile {i}: n={len(d)}, fold%={fold_pct:.3f}")

    first_half = events[: n // 2]
    second_half = events[n // 2 :]
    fold1 = sum(1 for e in first_half if e[3] == "folds") / len(first_half)
    fold2 = sum(1 for e in second_half if e[3] == "folds") / len(second_half)
    print(f"\nfirst half (n={len(first_half)}): fold%={fold1:.4f}")
    print(f"second half (n={len(second_half)}): fold%={fold2:.4f}")
    print(f"delta: {fold2 - fold1:+.4f}")

    import pandas as pd
    from scipy import stats

    df = pd.DataFrame(events, columns=["hand_index", "opp_seat", "opp_archetype", "response"])
    df.to_csv("/tmp/donk_bluff_events.csv", index=False)

    n_fold1 = sum(1 for e in first_half if e[3] == "folds")
    n_fold2 = sum(1 for e in second_half if e[3] == "folds")
    try:
        _, pvalue = stats.chi2_contingency(
            [[n_fold1, len(first_half) - n_fold1], [n_fold2, len(second_half) - n_fold2]]
        )[:2]
        print(f"chi2 p-value (first half vs second half): {pvalue:.4f}")
    except ValueError:
        print("chi2 test undefined (a cell is zero)")

    print("\nby archetype:")
    for arch in sorted(set(e[2] for e in events)):
        arch_events = [e for e in events if e[2] == arch]
        if len(arch_events) < 20:
            continue
        ah1 = arch_events[: len(arch_events) // 2]
        ah2 = arch_events[len(arch_events) // 2 :]
        f1 = sum(1 for e in ah1 if e[3] == "folds") / len(ah1)
        f2 = sum(1 for e in ah2 if e[3] == "folds") / len(ah2)
        print(f"  {arch}: n={len(arch_events)}, fold% first half={f1:.3f}, second half={f2:.3f}, delta={f2-f1:+.3f}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 80000
    main(n_hands=n)
