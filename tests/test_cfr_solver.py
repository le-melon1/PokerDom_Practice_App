from backend.solver.cfr_solver import solve_cfr_equilibrium


def test_cfr_solver_returns_strategy_and_value():
    result = solve_cfr_equilibrium(equity=0.6, pot=20.0, to_call=4.0, raise_amount=8.0, iterations=50)

    assert result["method"] == "cfr"
    assert set(result["hero_strategy"].keys()) == {"fold", "call", "raise"}
    assert result["hero_value"] is not None
    assert result["villain_strategy"]["call"] >= 0.0
