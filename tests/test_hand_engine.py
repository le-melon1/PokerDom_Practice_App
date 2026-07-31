from backend.engine.hand import Hand, IllegalAction
from backend.engine.models import Player


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
