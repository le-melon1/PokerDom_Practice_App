import pytest

from backend.solver.solver_tree import build_solver_tree


def test_solver_tree_projects_each_continuing_line_through_river():
    tree = build_solver_tree(
        street="flop",
        pot=10.0,
        to_call=2.0,
        equity=0.55,
        actions=[
            {"action": "fold", "amount": None},
            {"action": "call", "amount": 2.0},
            {"action": "raise", "amount": 8.0},
        ],
    )

    root = tree[0]
    assert root["summary"] == "current decision with projected future streets"
    fold, call, raise_branch = root["branches"]
    assert "next_node" not in fold
    assert call["next_node"]["street"] == "turn"
    turn_best = max(call["next_node"]["branches"], key=lambda item: item["ev"])
    assert turn_best["next_node"]["street"] == "river"
    assert "next_node" not in raise_branch
    assert [step["street"] for step in root["principal_variation"]] == ["flop", "turn", "river"]


def test_future_bet_uses_minimum_defense_frequency():
    tree = build_solver_tree(
        street="turn",
        pot=20.0,
        to_call=0.0,
        equity=0.5,
        actions=[{"action": "check", "amount": None}],
    )

    river = tree[0]["branches"][0]["next_node"]
    half_pot_like_bet = river["branches"][1]
    expected_fold_probability = half_pot_like_bet["amount"] / (river["pot"] + half_pot_like_bet["amount"])
    assert half_pot_like_bet["fold_probability"] == pytest.approx(expected_fold_probability, abs=0.001)