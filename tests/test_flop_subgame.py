import pytest

from backend.solver.flop_subgame import solve_flop_subgame, solve_postflop_subgame


def test_flop_subgame_samples_ranges_and_future_chance_cards_deterministically():
    kwargs = {
        "hero_range": ["AA", "AKs", "AQs"],
        "villain_range": ["QQ", "KQs", "JTs"],
        "flop": ["Ah", "Kd", "7c"],
        "pot": 12.0,
        "iterations": 120,
        "seed": 23,
        "focus_combo": ("Ac", "Kc"),
    }

    first = solve_flop_subgame(**kwargs)
    second = solve_flop_subgame(**kwargs)

    assert first == second
    assert first["method"] == "outcome-sampling-cfr"
    assert first["iterations"] == 120
    assert first["range_summary"]["hero_combos"] > 1
    assert first["range_summary"]["villain_combos"] > 1
    assert first["chance_nodes"]["sampled_turn_cards"] > 1
    assert first["chance_nodes"]["sampled_river_cards"] > 1
    assert first["focus_bucket"] == "medium"
    assert sum(first["focus_strategy"].values()) == pytest.approx(1.0)
    assert set(first["focus_action_values"]) == {"check", "bet_min", "bet_75", "all_in"}
    assert first["line_analysis"][0]["ev_loss"] == 0.0
    assert first["line_analysis"][0]["ev"] == pytest.approx(max(first["focus_action_values"].values()), abs=0.001)
    assert [step["street"] for step in first["principal_variation"]] == ["flop", "turn", "river"]


def test_flop_subgame_returns_normalized_strategies():
    result = solve_flop_subgame(
        hero_range=["AA", "AKs"],
        villain_range=["QQ", "KQs"],
        flop=["As", "8h", "3c"],
        pot=10.0,
        iterations=80,
        seed=7,
    )

    for strategy in result["street_strategies"].values():
        assert set(strategy) == {"check", "bet_min", "bet_75", "all_in"}
        assert sum(strategy.values()) == pytest.approx(1.0)
        assert all(0.0 <= probability <= 1.0 for probability in strategy.values())


def test_flop_subgame_rejects_non_flop_boards():
    with pytest.raises(ValueError, match="exactly three"):
        solve_flop_subgame(["AA"], ["KK"], ["Ah", "Kd"], pot=10.0)


def test_facing_bet_root_solves_fold_call_raise_and_all_in_response():
    result = solve_flop_subgame(
        hero_range=["AA", "AKs", "AQs"],
        villain_range=["QQ", "KQs", "JTs"],
        flop=["Ah", "8d", "3c"],
        pot=14.0,
        effective_stack=40.0,
        to_call=4.0,
        raise_investment=12.0,
        iterations=120,
        seed=29,
        focus_combo=("Ac", "Kc"),
    )

    assert result["root_mode"] == "facing_bet"
    assert set(result["focus_strategy"]) == {"fold", "call", "raise_min", "raise_75", "raise_all_in"}
    assert sum(result["focus_strategy"].values()) == pytest.approx(1.0)
    assert result["focus_action_values"]["fold"] == 0.0
    assert result["villain_response_actions"] == ["fold", "call", "reraise_all_in"]
    assert [step["street"] for step in result["principal_variation"]] == ["flop", "turn", "river"]


def test_facing_bet_raise_is_capped_at_effective_stack():
    result = solve_flop_subgame(
        hero_range=["AA", "AKs"],
        villain_range=["QQ", "KQs"],
        flop=["As", "8h", "3c"],
        pot=10.0,
        effective_stack=18.0,
        to_call=6.0,
        raise_investment=30.0,
        iterations=60,
        seed=7,
        focus_combo=("Ac", "Kc"),
    )

    assert result["raise_investment"] == 18.0
    assert all(investment <= 18.0 for investment in result["raise_investments"].values())
    assert result["raise_is_all_in"]
    assert result["all_in_response_actions"] == ["fold", "call"]


def test_turn_samples_only_river_chance_cards():
    result = solve_postflop_subgame(
        hero_range=["AA", "AKs"],
        villain_range=["QQ", "KQs"],
        board=["As", "8h", "3c", "Td"],
        pot=18.0,
        iterations=100,
        seed=11,
        focus_combo=("Ac", "Kc"),
    )

    assert result["start_street"] == "turn"
    assert result["chance_nodes"]["sampled_turn_cards"] == 0
    assert result["chance_nodes"]["sampled_river_cards"] > 1
    assert [step["street"] for step in result["principal_variation"]] == ["turn", "river"]


def test_river_uses_exact_board_without_chance_sampling():
    kwargs = {
        "hero_range": ["AA", "AKs"],
        "villain_range": ["QQ", "KQs"],
        "board": ["As", "8h", "3c", "Td", "2s"],
        "pot": 24.0,
        "iterations": 80,
        "seed": 13,
        "focus_combo": ("Ac", "Kc"),
    }
    first = solve_postflop_subgame(**kwargs)
    second = solve_postflop_subgame(**kwargs)

    assert first == second
    assert first["start_street"] == "river"
    assert first["chance_nodes"] == {"sampled_turn_cards": 0, "sampled_river_cards": 0}
    assert [step["street"] for step in first["principal_variation"]] == ["river"]