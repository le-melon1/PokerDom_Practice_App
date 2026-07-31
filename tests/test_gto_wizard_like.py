import pytest

from backend.solver.gto_wizard_like import solve_gto_wizard_like_strategy


def test_gto_wizard_like_strategy_returns_actions_and_weights():
    result = solve_gto_wizard_like_strategy(
        equity=0.6,
        pot=20.0,
        to_call=4.0,
        legal_actions={"min_raise_to": 8.0, "max_raise_to": 20.0, "can_check": True, "can_call": True},
        raise_sizes=[8.0, 14.0, 20.0],
    )

    assert result["recommended_action"] in {"check", "call", "raise"}
    assert result["action_weights"]
    assert result["ranked_actions"]
    assert result["tree"]
    assert len(result["line_analysis"]) >= 2
    assert result["line_analysis"][0]["action"] in {"check", "call", "raise"}
    assert result["line_analysis"][0]["ev_loss"] == 0.0
    assert result["line_analysis"][0]["category"] == "best"
    assert result["line_analysis"][1]["ev_loss"] >= 0.0
    assert result["line_analysis"][1]["explanation"]
    assert sum(result["action_weights"].values()) == pytest.approx(1.0)
    assert all(weight >= 0.0 for weight in result["action_weights"].values())


def test_call_ev_includes_the_call_in_the_final_pot():
    result = solve_gto_wizard_like_strategy(
        equity=0.4,
        pot=10.0,
        to_call=2.0,
        legal_actions={"min_raise_to": 20.0, "max_raise_to": 20.0, "can_check": False, "can_call": True},
        raise_sizes=[],
    )

    call = next(item for item in result["ranked_actions"] if item["action"] == "call")
    assert call["ev"] == pytest.approx(0.4 * 12.0 - 2.0)
