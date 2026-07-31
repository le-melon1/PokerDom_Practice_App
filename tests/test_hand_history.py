from types import SimpleNamespace

import pytest

from backend.ev.live_ev import LiveEVResult
from backend.hand_history import HandHistoryStore, grade_decision
from backend.engine.hand import Hand
from backend.engine.models import Player


def _ev(ev_call, to_call=2.0, pot_before=5.0):
    return LiveEVResult(
        street="preflop",
        pot_before=pot_before,
        to_call=to_call,
        equity_vs_range=0.4,
        opponent_range_size=50,
        ev_call=ev_call,
        breakeven_equity=to_call / (pot_before + to_call) if to_call else None,
        verdict="",
        confidence=0.5,
    )


def test_folding_a_plus_ev_call_is_flagged_as_mistake():
    d = grade_decision("preflop", 2.0, "fold", None, _ev(ev_call=1.5))
    assert d.is_mistake
    assert "фолд" in d.verdict


def test_folding_a_minus_ev_call_is_correct():
    d = grade_decision("preflop", 2.0, "fold", None, _ev(ev_call=-0.8))
    assert not d.is_mistake


def test_calling_a_minus_ev_spot_is_flagged():
    d = grade_decision("preflop", 2.0, "call", 2.0, _ev(ev_call=-0.5))
    assert d.is_mistake
    assert "-EV колл" in d.verdict


def test_calling_a_plus_ev_spot_is_not_flagged():
    d = grade_decision("preflop", 2.0, "call", 2.0, _ev(ev_call=0.9))
    assert not d.is_mistake


def test_folding_when_check_was_free_is_always_a_mistake():
    d = grade_decision("flop", 0.0, "fold", None, _ev(ev_call=None, to_call=0.0))
    assert d.is_mistake
    assert "бесплатным" in d.verdict


def test_check_is_neutral():
    d = grade_decision("flop", 0.0, "check", None, _ev(ev_call=None, to_call=0.0))
    assert not d.is_mistake


def test_raise_is_not_graded_since_sizing_ev_isnt_modeled():
    d = grade_decision("flop", 0.0, "raise", 6.0, _ev(ev_call=None, to_call=0.0))
    assert not d.is_mistake
    assert "не оценивается" in d.verdict


def test_trainer_grades_action_by_ev_loss():
    recommendation = SimpleNamespace(
        recommended_action="call",
        recommended_amount=None,
        best_ev=1.2,
        action_evs=[
            SimpleNamespace(action="call", amount=None, ev=1.2),
            SimpleNamespace(action="fold", amount=None, ev=0.0),
        ],
    )

    decision = grade_decision("preflop", 2.0, "fold", None, _ev(ev_call=1.2), recommendation)

    assert decision.solver_ev_loss == 1.2
    assert decision.trainer_grade == "mistake"
    assert decision.is_mistake


def test_trainer_uses_nearest_raise_sizing():
    recommendation = SimpleNamespace(
        recommended_action="raise",
        recommended_amount=6.0,
        best_ev=2.0,
        action_evs=[
            SimpleNamespace(action="raise", amount=6.0, ev=2.0),
            SimpleNamespace(action="raise", amount=12.0, ev=1.4),
        ],
    )

    decision = grade_decision("flop", 0.0, "raise", 11.0, _ev(ev_call=None, to_call=0.0), recommendation)

    assert decision.chosen_ev == 1.4
    assert decision.solver_ev_loss == pytest.approx(0.6)
    assert decision.trainer_grade == "mistake"


def _six_max_hand():
    players = [Player(seat=i + 1, name=f"P{i+1}", stack=200.0) for i in range(6)]
    return Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)


def test_store_records_and_lists_hands_with_mistake_counts():
    store = HandHistoryStore()
    hand = _six_max_hand()
    for seat in (4, 5, 6, 1):
        hand.apply_action(seat, "fold")
    hand.apply_action(2, "fold")  # SB folds, BB (seat 3) wins uncontested

    decisions = [grade_decision("preflop", 2.0, "fold", None, _ev(ev_call=1.2))]  # a deliberately-flagged decision
    store.record(hand, hand_number=1, hero_seat=1, decisions=decisions)

    summaries = store.list_summaries()
    assert len(summaries) == 1
    assert summaries[0]["hand_number"] == 1
    assert summaries[0]["mistake_count"] == 1

    entry = store.get(1)
    assert entry is not None
    assert entry.decisions[0].is_mistake


def test_store_caps_at_max_entries():
    store = HandHistoryStore(max_entries=3)
    for i in range(5):
        hand = _six_max_hand()
        for seat in (4, 5, 6, 1, 2):
            hand.apply_action(seat, "fold")
        store.record(hand, hand_number=i, hero_seat=1, decisions=[])

    assert len(store.entries) == 3
    assert [e.hand_number for e in store.entries] == [2, 3, 4]
