from backend.bots.behavior_clone import choose_bot_action
from backend.dossier import SeatDossier
from backend.engine.table import Table

# Regression tests for the "Hero-frequent-bluffer adaptation" feature in
# backend/bots/behavior_clone.py (see that module's docstring for the real
# PokerStars NL25 finding this implements: real players fold measurably less
# to a specific repeat opponent's bets within a session when that opponent's
# river bets have been getting shown down and losing meaningfully more often
# than the 75.3% population baseline). These tests check the plumbing
# (gating conditions, no-op when ungated) with a seeded sweep, not the
# real-world finding itself -- that's already verified in the sibling
# PokerDom_Microlimits_Analysis repo.

N_SEEDS = 4000


def _bot_facing_hero_preflop_raise():
    """Heads-up: hero (seat 1) acts first preflop and raises; seat 2 (the
    bot under test) faces that raise with no legal check."""
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=2)
    table.add_player(seat=1, name="Hero", stack=200.0)
    table.add_player(seat=2, name="Bot", stack=200.0)
    hand = table.start_new_hand()
    assert hand.current_actor() == 1
    hand.apply_action(1, "raise", 6.0)
    assert hand.current_actor() == 2
    assert not hand.legal_actions(2)["can_check"]
    return hand


def _bot_facing_non_hero_preflop_raise():
    """Three-handed: hero (seat 1) calls, seat 2 (a bot) raises, seat 3
    (the bot under test) faces THAT raise -- hero never bet this street."""
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=3)
    table.add_player(seat=1, name="Hero", stack=200.0)
    table.add_player(seat=2, name="BotA", stack=200.0)
    table.add_player(seat=3, name="BotB", stack=200.0)
    hand = table.start_new_hand()
    assert hand.current_actor() == 1
    hand.apply_action(1, "call")
    assert hand.current_actor() == 2
    hand.apply_action(2, "raise", 6.0)
    assert hand.current_actor() == 3
    assert not hand.legal_actions(3)["can_check"]
    return hand


def _actions(hand, seat, n_seeds, **kwargs):
    return [choose_bot_action(hand, seat, archetype="TAG", seed=s, **kwargs) for s in range(n_seeds)]


def _fold_rate(hand, seat, n_seeds, **kwargs):
    actions = _actions(hand, seat, n_seeds, **kwargs)
    return sum(1 for a, _ in actions if a == "fold") / n_seeds


def test_no_adaptation_when_hero_args_are_left_at_their_defaults():
    hand = _bot_facing_hero_preflop_raise()
    baseline = _actions(hand, 2, 200)
    explicit_none = _actions(hand, 2, 200, hero_seat=1, hero_dossier=None)
    assert baseline == explicit_none


def test_no_adaptation_when_river_showdown_sample_is_below_the_confidence_gate():
    # 3/3 river-aggression showdowns lost = 100% bluff rate, well above the
    # threshold -- but below HERO_BLUFFER_MIN_RIVER_SHOWDOWNS (4), exactly
    # the spurious-small-sample case the gate exists to prevent.
    thin_dossier = SeatDossier(river_aggression_showdowns=3, river_aggression_showdown_losses=3)
    assert thin_dossier.river_bluff_rate == 1.0

    hand = _bot_facing_hero_preflop_raise()
    with_thin_dossier = _fold_rate(hand, 2, N_SEEDS, hero_seat=1, hero_dossier=thin_dossier)
    without_dossier = _fold_rate(hand, 2, N_SEEDS, hero_seat=1, hero_dossier=None)
    assert with_thin_dossier == without_dossier


def test_no_adaptation_when_hero_is_not_read_as_a_frequent_bluffer():
    # Enough sample, but a bluff rate close to the 75.3% population baseline
    # -- not "meaningfully more," so the gate should stay closed.
    normal_dossier = SeatDossier(river_aggression_showdowns=8, river_aggression_showdown_losses=6)
    assert normal_dossier.river_bluff_rate == 0.75

    hand = _bot_facing_hero_preflop_raise()
    with_normal_dossier = _fold_rate(hand, 2, N_SEEDS, hero_seat=1, hero_dossier=normal_dossier)
    without_dossier = _fold_rate(hand, 2, N_SEEDS, hero_seat=1, hero_dossier=None)
    assert with_normal_dossier == without_dossier


def test_no_adaptation_when_the_bet_being_faced_is_not_from_hero():
    hand = _bot_facing_non_hero_preflop_raise()
    bluffer_dossier = SeatDossier(river_aggression_showdowns=5, river_aggression_showdown_losses=5)

    with_dossier = _fold_rate(hand, 3, N_SEEDS, hero_seat=1, hero_dossier=bluffer_dossier)
    without_dossier = _fold_rate(hand, 3, N_SEEDS, hero_seat=1, hero_dossier=None)
    assert with_dossier == without_dossier


def test_fold_rate_drops_by_roughly_the_measured_magnitude_when_fully_gated():
    hand = _bot_facing_hero_preflop_raise()
    bluffer_dossier = SeatDossier(river_aggression_showdowns=5, river_aggression_showdown_losses=5)
    assert bluffer_dossier.river_bluff_rate == 1.0

    adapted = _fold_rate(hand, 2, N_SEEDS, hero_seat=1, hero_dossier=bluffer_dossier)
    baseline = _fold_rate(hand, 2, N_SEEDS, hero_seat=1, hero_dossier=None)

    # Targets a 0.93pp absolute drop (HERO_BLUFFER_FOLD_REDUCTION_PP) --
    # allow a wide band since this is probability MASS shifted in a
    # possibly-unnormalized weight space, not guaranteed to land at exactly
    # 0.93pp of the final sampling distribution.
    assert 0.001 <= baseline - adapted <= 0.03
