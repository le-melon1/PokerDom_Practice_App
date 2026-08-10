from backend.dossier import SeatDossier, TableDossier
from backend.engine.hand import Hand
from backend.engine.models import Player


def make_players(n, stack=200.0):
    return [Player(seat=i + 1, name=f"P{i+1}", stack=stack) for i in range(n)]


def _river_showdown_hand(bettor_wins: bool):
    """Heads-up hand checked down to the river, where seat 1 bets and seat 2
    calls -- a real, contested showdown. Hole cards/board are overridden
    (same pattern as tests/test_abc_bot.py) so the outcome is deterministic:
    seat 1 has ace-high (nothing), seat 2 has aces-and-kings two pair --
    seat 2 always wins this specific setup unless the roles are swapped."""
    players = make_players(2)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(1, "call")  # heads-up: button/SB acts first, completes
    hand.apply_action(2, "check")  # BB checks option
    assert hand.street == "flop"
    hand.apply_action(hand.current_actor(), "check")
    hand.apply_action(hand.current_actor(), "check")
    assert hand.street == "turn"
    hand.apply_action(hand.current_actor(), "check")
    hand.apply_action(hand.current_actor(), "check")
    assert hand.street == "river"

    hand.board = ["Ah", "Kd", "2h", "5s", "9c"]
    weak_hole, strong_hole = ["3c", "4d"], ["Ac", "Kc"]
    if bettor_wins:
        hand.players[1].hole_cards = strong_hole
        hand.players[2].hole_cards = weak_hole
    else:
        hand.players[1].hole_cards = weak_hole
        hand.players[2].hole_cards = strong_hole

    river_bettor = hand.current_actor()
    hand.apply_action(river_bettor, "bet", amount=5.0)
    hand.apply_action(hand.current_actor(), "call")
    assert hand.finished
    return hand, river_bettor


def test_river_aggressor_who_loses_a_real_showdown_is_tracked_as_a_loss():
    hand, river_bettor = _river_showdown_hand(bettor_wins=False)
    dossier = TableDossier()
    dossier.record_hand(hand)

    d = dossier.by_seat[river_bettor]
    assert d.river_aggression_showdowns == 1
    assert d.river_aggression_showdown_losses == 1
    assert d.river_bluff_rate == 1.0


def test_river_aggressor_who_wins_a_real_showdown_is_not_tracked_as_a_loss():
    hand, river_bettor = _river_showdown_hand(bettor_wins=True)
    dossier = TableDossier()
    dossier.record_hand(hand)

    d = dossier.by_seat[river_bettor]
    assert d.river_aggression_showdowns == 1
    assert d.river_aggression_showdown_losses == 0
    assert d.river_bluff_rate == 0.0


def test_uncalled_bet_is_not_counted_as_a_river_showdown():
    players = make_players(2)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(1, "call")  # heads-up: button/SB acts first, completes
    hand.apply_action(2, "check")  # BB checks option
    assert hand.street == "flop"
    hand.apply_action(hand.current_actor(), "check")
    hand.apply_action(hand.current_actor(), "check")
    assert hand.street == "turn"
    hand.apply_action(hand.current_actor(), "check")
    hand.apply_action(hand.current_actor(), "check")
    assert hand.street == "river"

    river_bettor = hand.current_actor()
    hand.apply_action(river_bettor, "bet", amount=5.0)
    hand.apply_action(hand.current_actor(), "fold")  # no real showdown -- uncalled bet
    assert hand.finished

    dossier = TableDossier()
    dossier.record_hand(hand)
    d = dossier.by_seat.get(river_bettor)
    assert d is None or d.river_aggression_showdowns == 0


def test_river_bluff_rate_defaults_to_zero_with_no_showdowns():
    assert SeatDossier().river_bluff_rate == 0.0
