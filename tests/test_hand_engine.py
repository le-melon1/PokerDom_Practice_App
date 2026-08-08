import random

import pytest

from backend.engine.hand import Hand, IllegalAction
from backend.engine.models import Player
from backend.engine.table import Table


def make_players(n, stack=200.0):
    return [Player(seat=i + 1, name=f"P{i+1}", stack=stack) for i in range(n)]


def test_blinds_posted_correctly_heads_up():
    players = make_players(2)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    # heads-up: button (seat 1) posts SB, seat 2 posts BB
    assert hand.players[1].street_contributed == 1.0
    assert hand.players[2].street_contributed == 2.0
    assert hand.current_bet == 2.0
    # heads-up preflop: button/SB acts first
    assert hand.current_actor() == 1


def test_blinds_posted_correctly_6max():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    assert hand.players[2].street_contributed == 1.0  # SB
    assert hand.players[3].street_contributed == 2.0  # BB
    # preflop action starts at seat 4 (UTG, left of BB)
    assert hand.current_actor() == 4


def test_everyone_folds_to_button_wins_uncontested():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    for seat in (4, 5, 6, 1):
        hand.apply_action(seat, "fold")
    # only SB (2) and BB (3) remain; SB folds too
    hand.apply_action(2, "fold")
    assert hand.finished
    assert hand.result.payouts[3] == 3.0  # wins the sb+bb dead money
    assert hand.players[3].stack == 200.0 - 2.0 + 3.0


def test_illegal_action_wrong_turn():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    try:
        hand.apply_action(1, "fold")  # seat 1 isn't first to act preflop
        assert False, "should have raised"
    except IllegalAction:
        pass


def test_full_hand_reaches_showdown_and_pot_conserved():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    total_stacks_before = sum(p.stack for p in hand.players.values()) + 3.0  # blinds already posted

    # everyone calls/checks down to showdown
    hand.apply_action(4, "call")
    hand.apply_action(5, "call")
    hand.apply_action(6, "call")
    hand.apply_action(1, "call")
    hand.apply_action(2, "call")  # SB completes
    hand.apply_action(3, "check")  # BB checks option
    assert hand.street == "flop"

    guard = 0
    while not hand.finished and guard < 100:
        hand.apply_action(hand.current_actor(), "check")
        guard += 1

    assert hand.finished
    total_stacks_after = sum(p.stack for p in hand.players.values())
    assert abs(total_stacks_after - total_stacks_before) < 1e-6


def test_all_in_creates_side_pot():
    players = make_players(3, stack=200.0)
    players[2].stack = 10.0  # seat 3 is short-stacked
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    # 3-handed: seat 2=SB, seat3=BB, action starts seat1 (UTG/button acts first 3-handed... )
    actor = hand.current_actor()
    hand.apply_action(actor, "raise", amount=50.0)
    remaining = [s for s in (1, 2, 3) if s != actor]
    for s in remaining:
        if hand.current_actor() == s and not hand.finished:
            hand.apply_action(s, "call")

    assert hand.players[3].all_in
    assert hand.players[3].stack == 0.0


def test_min_raise_enforced():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    try:
        hand.apply_action(4, "raise", amount=3.0)  # less than min raise (2->4)
        assert False, "should have raised IllegalAction"
    except IllegalAction:
        pass
    hand.apply_action(4, "raise", amount=6.0)  # legal: raise to 6 (increment of 4 >= bb)
    assert hand.current_bet == 6.0


def test_no_flop_no_drop():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0, rake_percent=0.05, rake_cap_bb=5.0)
    for seat in (4, 5, 6, 1):
        hand.apply_action(seat, "fold")
    hand.apply_action(2, "fold")  # SB folds, BB wins uncontested preflop -- no flop was seen
    assert hand.finished
    assert hand.result.rake == 0.0
    assert hand.result.payouts[3] == 3.0  # full dead money, untaxed


def test_rake_taken_from_pot_once_flop_is_seen():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0, rake_percent=0.05, rake_cap_bb=5.0)
    hand.apply_action(4, "call")
    hand.apply_action(5, "call")
    hand.apply_action(6, "call")
    hand.apply_action(1, "call")
    hand.apply_action(2, "call")
    hand.apply_action(3, "check")
    assert hand.street == "flop"

    # everyone folds to the first flop bettor -- uncontested, but a flop was seen.
    # A bet/raise reopens action in the street's real order continuing right
    # after the bettor (postflop order here is [2,3,4,5,6,1]; seat 2 bets, so
    # the rest owe a decision in the order 3,4,5,6,1).
    hand.apply_action(2, "bet", amount=6.0)
    for seat in (3, 4, 5, 6, 1):
        hand.apply_action(seat, "fold")

    assert hand.finished
    total_pot = 12.0 + 6.0  # 6 players x 2bb preflop + the flop bet
    expected_rake = min(total_pot * 0.05, 5.0)
    assert abs(hand.result.rake - expected_rake) < 1e-6
    assert hand.result.payouts[2] == total_pot - expected_rake


def test_raise_reopens_action_in_true_order_not_button_first_rotation():
    # Regression test for a real bug: after seat 4 (UTG) raises preflop, the
    # remaining players in true table order are 5, 6 (still owed a decision
    # before the button), then 1 (BTN), 2 (SB), 3 (BB). The old buggy code
    # rebuilt the queue from a button-first rotation ([1,2,3,4,5,6] minus the
    # raiser), which incorrectly let seat 1 (the button) act before 5 and 6 --
    # exactly the "why haven't bot5/bot6 acted yet" bug a real user hit.
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    assert hand.current_actor() == 4
    hand.apply_action(4, "raise", amount=6.0)
    assert hand.current_actor() == 5
    hand.apply_action(5, "fold")
    assert hand.current_actor() == 6
    hand.apply_action(6, "fold")
    assert hand.current_actor() == 1  # only now does the button get to act


def test_rake_capped_and_split_across_side_pots_at_showdown():
    players = make_players(3, stack=200.0)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0, rake_percent=0.05, rake_cap_bb=5.0)
    actor = hand.current_actor()
    hand.apply_action(actor, "raise", amount=100.0)
    remaining = [s for s in (1, 2, 3) if s != actor]
    for s in remaining:
        if hand.current_actor() == s and not hand.finished:
            hand.apply_action(s, "call")

    guard = 0
    while not hand.finished and guard < 20:
        hand.apply_action(hand.current_actor(), "check")
        guard += 1

    assert hand.finished
    total_pot = 300.0  # all three stacks of 100 in
    cap = 5.0 * 2.0
    assert hand.result.rake == cap  # 5% of 300 (=15) is above the 5bb cap, so it's capped
    total_paid_out = sum(hand.result.payouts.values())
    assert abs(total_paid_out - (total_pot - cap)) < 1e-6


def test_folding_the_uncalled_top_of_a_bet_refunds_it_instead_of_vanishing():
    # Regression test for a real bug (found 2026-08-08 by scripts/
    # smoke_test_table.py -- random actions lost hundreds of chips within a
    # handful of hands, and it reproduced with real bots too, not just
    # randomness). A bet/raise bigger than any live opponent's remaining
    # stack creates a side-pot LAYER whose only eligible contributor is the
    # bettor themselves. If that same player later folds (fully legal --
    # nothing stops folding when you could check for free, e.g. a random
    # policy or a misclick), the old code did `continue` on that layer when
    # it found no live eligible player, silently dropping the chips instead
    # of returning them -- the poker-standard "uncalled bet" case, just
    # discovered late (at final payout) instead of immediately.
    #
    # Three players: P1=200 (will bet big, then fold), P2=20 (short, calls
    # all-in early, stays passive to showdown), P3=90 (medium, ends up
    # all-in-for-less against P1's big bet, stays live to showdown).
    players = [
        Player(seat=1, name="P1", stack=200.0),
        Player(seat=2, name="P2", stack=20.0),
        Player(seat=3, name="P3", stack=90.0),
    ]
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    stacks_before_hand = {1: 200.0, 2: 20.0, 3: 90.0}

    hand.apply_action(1, "call")
    hand.apply_action(2, "call")
    hand.apply_action(3, "check")
    assert hand.street == "flop"

    hand.apply_action(2, "raise", amount=18.0)  # P2 shoves their last 18 (all-in)
    hand.apply_action(3, "call")
    hand.apply_action(1, "call")
    assert hand.street == "turn"

    hand.apply_action(3, "check")
    hand.apply_action(1, "raise", amount=170.0)  # far more than P3 can ever call
    hand.apply_action(3, "call")  # all-in for less -- only 70 of the 150 owed
    assert hand.street == "river"
    assert not hand.finished  # P1 still has chips and gets one more decision

    hand.apply_action(1, "fold")  # legal even though checking was free
    assert hand.finished

    # The layer only P1 ever reached (P1's total 190 vs P3's cap at 90) has
    # to come back to P1 -- nobody else was ever eligible for it, so there's
    # no one to award it to via showdown, and it was never really "at risk."
    assert abs(hand.result.payouts[1] - 100.0) < 1e-6

    total_end = sum(p.stack for p in hand.players.values())
    assert abs(total_end - sum(stacks_before_hand.values())) < 1e-6


def _random_legal_action(hand, seat):
    legal = hand.legal_actions(seat)
    choices = ["fold"]
    if legal["can_check"]:
        choices.append("check")
    if legal["can_call"]:
        choices.append("call")
    if legal["max_raise_to"] > hand.current_bet:
        choices.append("raise")
    action = random.choice(choices)
    if action == "raise":
        lo, hi = legal["min_raise_to"], legal["max_raise_to"]
        return action, round(random.uniform(lo, hi), 2)
    return action, None


@pytest.mark.parametrize("n_players", [2, 3, 4, 5, 6, 7, 8])
def test_chip_conservation_under_random_play(n_players):
    # Property-based regression test standing in for scripts/
    # smoke_test_table.py, which is what actually caught the real
    # uncalled-side-pot chip-loss bug fixed 2026-08-08 (hand-picked
    # scenario tests, however thorough, hadn't hit it in many sessions of
    # this project's history -- adversarial random play across many table
    # sizes and stack depths found it within a couple dozen hands). Keeping
    # a seeded, bounded version of that here means this class of bug can't
    # silently regress again without pytest catching it. random.choice on
    # a raise-to amount can occasionally land a hair below the precise
    # legal minimum (float rounding) -- IllegalAction there just means
    # "try folding instead," exactly like the live bots' own fallback in
    # simulate_abc_bot.py, not a bug in itself.
    random.seed(n_players)
    stacks = [random.choice([20.0, 50.0, 200.0, 500.0]) for _ in range(n_players)]
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=n_players, rake_percent=0.05, rake_cap_bb=5.0)
    for i in range(n_players):
        table.add_player(seat=i + 1, name=f"P{i+1}", stack=stacks[i])

    total_start = sum(p.stack for p in table.players.values())
    rake_collected = 0.0

    for _ in range(300):
        if len([p for p in table.players.values() if p.stack > 0]) < 2:
            break
        try:
            hand = table.start_new_hand()
        except RuntimeError:
            break
        guard = 0
        while not hand.finished and guard < 300:
            seat = hand.current_actor()
            if seat is None:
                break
            action, amount = _random_legal_action(hand, seat)
            try:
                hand.apply_action(seat, action, amount)
            except IllegalAction:
                hand.apply_action(seat, "fold")
            guard += 1
        assert guard < 300, "hand did not finish within 300 actions -- possible infinite loop"
        if not hand.finished:
            continue
        rake_collected += hand.result.rake if hand.result else 0.0
        total_now = sum(p.stack for p in table.players.values())
        expected = total_start - rake_collected
        assert abs(total_now - expected) < 1e-4, (
            f"chip conservation violated: total={total_now:.4f} expected={expected:.4f}"
        )
