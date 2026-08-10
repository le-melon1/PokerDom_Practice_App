import pytest

from backend.dossier import SeatDossier
from backend.engine.table import Table
from backend.ev.live_ev import (
    _cached_postflop_subgame,
    estimate_live_ev,
    recommend_gto_action,
    solve_two_action_equilibrium,
    solve_three_action_equilibrium,
)


def _get_hero_facing_raise():
    """Deterministic-ish setup: fold everyone to hero, leaving one raiser live,
    with hero facing a decision. Retries a few button positions/seed states
    since who's live depends on the random deal only via hole cards, not
    action -- actions here are scripted, so this is fully deterministic."""
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=6)
    for i in range(6):
        table.add_player(seat=i + 1, name=f"Bot{i+1}", stack=200.0)
    hand = table.start_new_hand()

    guard = 0
    while not hand.finished and guard < 20:
        seat = hand.current_actor()
        if seat is None or seat == 1:
            break
        hand.apply_action(seat, "fold")
        guard += 1
    return hand


def _get_heads_up_hero_facing_flop_bet():
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=2)
    table.add_player(seat=1, name="Hero", stack=80.0)
    table.add_player(seat=2, name="Villain", stack=80.0)
    hand = table.start_new_hand()
    hand.apply_action(1, "call")
    hand.apply_action(2, "check")
    assert hand.street == "flop" and hand.current_actor() == 2
    hand.apply_action(2, "bet", 4.0)
    assert hand.current_actor() == 1
    return hand


def _get_heads_up_hero_checked_to(street):
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=2)
    table.add_player(seat=1, name="Hero", stack=80.0)
    table.add_player(seat=2, name="Villain", stack=80.0)
    hand = table.start_new_hand()
    hand.apply_action(1, "call")
    hand.apply_action(2, "check")
    while hand.street != street:
        hand.apply_action(2, "check")
        hand.apply_action(1, "check")
    hand.apply_action(2, "check")
    assert hand.current_actor() == 1
    return hand


def test_wider_villain_range_increases_equity_and_can_flip_ev():
    hand = _get_hero_facing_raise()
    assert hand.current_actor() == 1 and not hand.finished

    r_nit = estimate_live_ev(hand, 1, opponent_archetype="Nit", equity_trials=800)
    r_maniac = estimate_live_ev(hand, 1, opponent_archetype="Maniac", equity_trials=800)

    assert r_maniac.opponent_range_size > r_nit.opponent_range_size
    assert r_maniac.equity_vs_range > r_nit.equity_vs_range


def test_solve_two_action_equilibrium_returns_balanced_probs_for_symmetric_matrix():
    matrix = [[1.0, -1.0], [-1.0, 1.0]]
    hero_probs, villain_probs = solve_two_action_equilibrium(matrix)

    assert hero_probs == pytest.approx([0.5, 0.5])
    assert villain_probs == pytest.approx([0.5, 0.5])


def test_recommend_gto_action_returns_ranked_actions_and_best_ev():
    hand = _get_hero_facing_raise()
    rec = recommend_gto_action(hand, 1, opponent_archetype="Nit", equity_trials=400)

    assert rec.recommended_action in {"fold", "call", "raise", "bet", "check"}
    assert len(rec.action_evs) >= 2
    assert rec.best_ev is not None
    assert rec.action_evs[0].ev is not None
    assert abs(rec.best_ev - max(item.ev for item in rec.action_evs)) < 1e-9
    assert rec.gto_equilibrium is not None


def test_recommend_gto_action_preflop_matches_the_validated_abc_strategy():
    # 2026-08-10: preflop recommendations come from the already-validated
    # ABC strategy (backend/bots/abc_bot.py), not solve_gto_wizard_like_
    # strategy's own pick -- see live_ev.py's _abc_strategy_preflop_action
    # docstring for why (that heuristic has no reliable preflop
    # fold-equity data and, tested with the one real table available,
    # measured a 100%-raise over-correction). Verify the final
    # recommendation matches choose_abc_action's independent computation
    # for this exact spot, rather than wizard_like's line_analysis.
    from backend.bots.abc_bot import choose_abc_action

    hand = _get_hero_facing_raise()
    rec = recommend_gto_action(hand, 1, opponent_archetype="Nit", equity_trials=400)

    live_opponents = [s for s, p in hand.players.items() if p.in_hand and s != 1]
    expected_action, expected_amount = choose_abc_action(
        hand, 1, opponent_archetypes={s: "Nit" for s in live_opponents}
    )
    assert rec.recommended_action == expected_action
    assert rec.recommended_amount == expected_amount


def test_heads_up_flop_facing_bet_uses_range_cfr_defense_actions():
    hand = _get_heads_up_hero_facing_flop_bet()
    legal = hand.legal_actions(1)
    rec = recommend_gto_action(hand, 1, opponent_archetype="TAG", equity_trials=120)
    subgame = rec.gto_equilibrium["flop_subgame"]

    assert subgame["root_mode"] == "facing_bet"
    assert set(subgame["focus_strategy"]) == {
        "fold",
        "call",
        "raise_min",
        "raise_75",
        "raise_all_in",
    }
    assert {item.action for item in rec.action_evs} == {"fold", "call", "raise"}
    raise_amounts = sorted(item.amount for item in rec.action_evs if item.action == "raise")
    assert raise_amounts[0] == legal["min_raise_to"]
    assert raise_amounts[-1] == legal["max_raise_to"]
    abstract_best = subgame["line_analysis"][0]["action"]
    assert rec.recommended_action == ("raise" if abstract_best.startswith("raise_") else abstract_best)


@pytest.mark.parametrize("street, board_length", [("turn", 4), ("river", 5)])
def test_heads_up_later_street_uses_range_cfr(street, board_length):
    hand = _get_heads_up_hero_checked_to(street)
    rec = recommend_gto_action(hand, 1, opponent_archetype="TAG", equity_trials=100)
    subgame = rec.gto_equilibrium["flop_subgame"]

    assert len(hand.board) == board_length
    assert subgame["start_street"] == street
    assert subgame["root_mode"] == "checked_to"
    assert {item.action for item in rec.action_evs} == {"check", "raise"}
    if street == "turn":
        assert subgame["chance_nodes"]["sampled_river_cards"] > 1
    else:
        assert subgame["chance_nodes"] == {"sampled_turn_cards": 0, "sampled_river_cards": 0}


def test_identical_live_postflop_solve_hits_cache():
    _cached_postflop_subgame.cache_clear()
    hand = _get_heads_up_hero_checked_to("turn")

    first = recommend_gto_action(hand, 1, opponent_archetype="TAG", equity_trials=80)
    second = recommend_gto_action(hand, 1, opponent_archetype="TAG", equity_trials=80)

    assert not first.gto_equilibrium["flop_subgame"]["cache_hit"]
    assert second.gto_equilibrium["flop_subgame"]["cache_hit"]


def test_solve_three_action_equilibrium_returns_valid_mixed_strategy():
    matrix = [
        [0.0, 1.0, -1.0],
        [-1.0, 0.0, 1.0],
        [1.0, -1.0, 0.0],
    ]
    hero_probs, villain_probs = solve_three_action_equilibrium(matrix)

    assert hero_probs == pytest.approx([1 / 3, 1 / 3, 1 / 3], abs=1e-9)
    assert villain_probs == pytest.approx([1 / 3, 1 / 3, 1 / 3], abs=1e-9)


def test_breakeven_equity_matches_pot_odds_formula():
    hand = _get_hero_facing_raise()
    r = estimate_live_ev(hand, 1, opponent_archetype=None, equity_trials=500)
    expected = r.to_call / (r.pot_before + r.to_call)
    assert abs(r.breakeven_equity - expected) < 1e-9


def test_no_call_needed_when_checked_to():
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=6)
    for i in range(6):
        table.add_player(seat=i + 1, name=f"Bot{i+1}", stack=200.0)
    hand = table.start_new_hand()
    # everyone limps/checks to the BB option, then BB checks -> flop, hero (whoever) faces no bet
    guard = 0
    while not hand.finished and hand.street == "preflop" and guard < 20:
        seat = hand.current_actor()
        legal = hand.legal_actions(seat)
        hand.apply_action(seat, "check" if legal["can_check"] else "call")
        guard += 1

    assert hand.street in ("flop", "turn", "river") or hand.finished
    if not hand.finished:
        seat = hand.current_actor()
        r = estimate_live_ev(hand, seat, opponent_archetype=None, equity_trials=500)
        assert r.to_call == 0
        assert r.ev_call is None


class _FakeDossier:
    def __init__(self, by_seat):
        self.by_seat = by_seat


def test_auto_mode_with_no_dossier_data_has_zero_confidence():
    hand = _get_hero_facing_raise()
    r = estimate_live_ev(hand, 1, opponent_archetype=None, dossier=None, equity_trials=500)
    assert r.confidence == 0.0
    assert "мало данных" in r.confidence_note


def test_auto_mode_leans_toward_observed_session_stats_as_hands_accumulate():
    hand = _get_hero_facing_raise()
    live_opp_seats = [s for s, p in hand.players.items() if p.in_hand and s != 1]

    # Every live opponent observed for a long, maniac-like session (very high
    # VPIP) should widen the auto-mode range and raise reported confidence
    # relative to freshly-sat, unobserved opponents. Overall confidence is the
    # MINIMUM across live opponents by design (see estimate_live_ev: a single
    # still-unknown player should keep the read cautious), so every live seat
    # needs dossier data for this comparison to isolate the effect.
    maniac_dossier = _FakeDossier({s: SeatDossier(hands_seen=200, vpip_hands=180) for s in live_opp_seats})
    fresh_dossier = _FakeDossier({s: SeatDossier(hands_seen=0) for s in live_opp_seats})

    r_seasoned = estimate_live_ev(hand, 1, opponent_archetype=None, dossier=maniac_dossier, equity_trials=800)
    r_fresh = estimate_live_ev(hand, 1, opponent_archetype=None, dossier=fresh_dossier, equity_trials=800)

    assert r_seasoned.confidence > r_fresh.confidence
    # A wider (more maniac-like) villain range includes more weak hands, which
    # raises hero's equity against it -- same direction already established
    # by test_wider_villain_range_increases_equity_and_can_flip_ev above.
    assert r_seasoned.opponent_range_size >= r_fresh.opponent_range_size
    assert r_seasoned.equity_vs_range >= r_fresh.equity_vs_range


def test_recommend_gto_action_survives_a_subcent_call_amount():
    # Regression test for a real crash found 2026-08-08 by a random-action
    # stress test against the live EV/GTO code (not a hand-picked scenario --
    # this class of bug hides from those). Root cause: flop_subgame.py's
    # solver decides "am I facing a bet" from the ROUNDED call amount it's
    # given (facing_bet = to_call > 0 after round(..., 2)), but
    # _solve_live_postflop_subgame used to decide which action_amounts
    # branch to build from the RAW, unrounded legal["can_call"]. A sub-cent
    # residue call amount (a real possibility after several streets of
    # pot-fraction sizing math) rounds to 0.00 -- the solver then returns
    # raise_investments=None (its "checked to" path), but the wrapper still
    # took the can_call branch and indexed straight into it, crashing with
    # "'NoneType' object is not subscriptable". Fixed by rounding once and
    # using that single rounded value to decide both the solver's inputs and
    # the wrapper's own branch, so they can never disagree.
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=2)
    table.add_player(seat=1, name="Hero", stack=200.0)
    table.add_player(seat=2, name="Villain", stack=200.0)
    hand = table.start_new_hand()
    hand.apply_action(1, "call")
    hand.apply_action(2, "check")
    assert hand.street == "flop"
    hand.players[1].hole_cards = ["Ah", "Kd"]
    hand.players[2].hole_cards = ["2c", "7s"]
    # Engineer the exact edge case: a real but sub-cent-after-rounding call
    # amount, the kind real street-by-street pot arithmetic can produce.
    hand.current_bet = hand.players[1].street_contributed + 0.003
    assert 0 < hand.legal_actions(1)["call_amount"] < 0.005

    base = estimate_live_ev(hand, 1, opponent_archetype="TAG", equity_trials=50)
    rec = recommend_gto_action(hand, 1, opponent_archetype="TAG", equity_trials=50, base=base)
    assert rec.recommended_action in {"fold", "check", "call", "raise", "bet"}
