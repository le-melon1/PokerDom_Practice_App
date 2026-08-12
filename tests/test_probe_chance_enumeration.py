import pytest

import backend.bots.abc_bot as abc_bot
from scripts import probe_chance_enumeration as probe


def test_adaptive_stop_accepts_negative_delta_once_ci_is_below_loss():
    assert (
        probe._adaptive_stop_reason(
            n_hands=10_000,
            divergent=30,
            enum_delta=-4.0,
            enum_ci=3.9,
            min_hands=10_000,
            max_hands=500_000,
            max_zero_divergent_hands=50_000,
            min_divergent=30,
            max_divergent=2_000,
            target_ci=1.0,
            effect_ratio=0.5,
        )
        == "confirmed_negative"
    )


def test_adaptive_stop_keeps_positive_delta_on_stricter_precision_bar():
    assert (
        probe._adaptive_stop_reason(
            n_hands=10_000,
            divergent=30,
            enum_delta=4.0,
            enum_ci=1.5,
            min_hands=10_000,
            max_hands=500_000,
            max_zero_divergent_hands=50_000,
            min_divergent=30,
            max_divergent=2_000,
            target_ci=1.0,
            effect_ratio=0.5,
        )
        is None
    )


def test_adaptive_stop_caps_rules_that_never_diverge():
    assert (
        probe._adaptive_stop_reason(
            n_hands=50_000,
            divergent=0,
            enum_delta=0.0,
            enum_ci=0.0,
            min_hands=10_000,
            max_hands=500_000,
            max_zero_divergent_hands=50_000,
            min_divergent=30,
            max_divergent=2_000,
            target_ci=1.0,
            effect_ratio=0.5,
        )
        == "no_divergent_hands"
    )


def test_historical_v11_comparison_is_not_current_defaults_overlay():
    comparison = probe._build_comparison("v11-multiway-aware", "historical")

    assert comparison.baseline["USE_WIDE_VALUE_3BET"] is True
    assert comparison.baseline["STEAL_WIDER_VS_NIT"] is False
    assert comparison.baseline["ISO_RAISE_OVER_LIMPERS"] is False
    assert comparison.baseline["SQUEEZE_WIDER_RANGE"] is False
    assert comparison.baseline["MULTIWAY_DISABLE_AIR_CBET"] is False
    assert comparison.treatment["MULTIWAY_DISABLE_AIR_CBET"] is True


def test_v9_historical_probe_is_rejected_because_opponent_awareness_is_always_on():
    with pytest.raises(ValueError, match="v9 predates the v10 opponent-aware"):
        probe._build_comparison("v9-wide-3bet", "historical")


def test_ablation_compares_current_full_model_to_rule_removed():
    comparison = probe._build_comparison("v17-donk-bluff", "ablation")

    assert comparison.baseline["DONK_BLUFF_VS_TIGHT"] is True
    assert comparison.treatment["DONK_BLUFF_VS_TIGHT"] is False
    assert "without rule - full" in comparison.label


def test_ablation_can_disable_the_v10_opponent_awareness_pseudo_rule():
    comparison = probe._build_comparison("v10-opponent-aware", "ablation")

    assert comparison.baseline["OPPONENT_AWARE_ARCHETYPES"] is True
    assert comparison.treatment["OPPONENT_AWARE_ARCHETYPES"] is False


def test_rule_ids_cover_current_ablation_rule_units():
    groups = probe._all_test_groups()
    expected = {
        "r01-calling-raises": ["ALLOW_CALLING_RAISES"],
        "r02-unconditional-cbet": ["UNCONDITIONAL_FLOP_CBET"],
        "r03-opponent-aware-loose-call": ["OPPONENT_AWARE_ARCHETYPES"],
        "r04-wide-value-3bet": ["USE_WIDE_VALUE_3BET"],
        "r05-steal-wide-vs-nit": ["STEAL_WIDER_VS_NIT"],
        "r06-size-up-vs-nit-tag": ["SIZING_TARGET_ARCHETYPES"],
        "r07-wider-3bet-vs-loose": ["WIDER_3BET_VS_LOOSE"],
        "r08-size-up-turn": ["SIZE_UP_ON_TURN"],
        "r09-iso-raise-limpers": ["ISO_RAISE_OVER_LIMPERS"],
        "r10-donk-bluff-vs-tight": ["DONK_BLUFF_VS_TIGHT"],
        "r11-hero-pot-damping": ["HERO_PROGRESSIVE_POT_DAMPING"],
    }

    assert {name: groups[name][0] for name in expected} == expected


def test_rule_ids_match_legacy_v_aliases_for_same_flags():
    groups = probe._all_test_groups()
    aliases = {
        "r01-calling-raises": "v3-calling-raises",
        "r02-unconditional-cbet": "v6-unconditional-cbet",
        "r03-opponent-aware-loose-call": "v10-opponent-aware",
        "r04-wide-value-3bet": "v9-wide-3bet",
        "r05-steal-wide-vs-nit": "v14-steal-wide",
        "r06-size-up-vs-nit-tag": "v14-size-target",
        "r07-wider-3bet-vs-loose": "v15-loose-3bet",
        "r08-size-up-turn": "v15-turn-size",
        "r09-iso-raise-limpers": "v16-iso-limpers",
        "r10-donk-bluff-vs-tight": "v17-donk-bluff",
        "r11-hero-pot-damping": "v19-hero-pot-damping",
    }

    for rule_id, legacy_id in aliases.items():
        assert groups[rule_id][0] == groups[legacy_id][0]


def test_ablation_can_use_new_rule_ids():
    comparison = probe._build_comparison("r10-donk-bluff-vs-tight", "ablation")

    assert comparison.baseline["DONK_BLUFF_VS_TIGHT"] is True
    assert comparison.treatment["DONK_BLUFF_VS_TIGHT"] is False


def test_parse_archetypes_rejects_unknown_values():
    assert probe._parse_archetypes("Nit,TAG") == ["Nit", "TAG"]
    with pytest.raises(ValueError, match="unknown archetypes"):
        probe._parse_archetypes("Nit,Wizard")


def test_conditioned_probe_state_restricts_turnover_archetypes():
    _, _, base_turnover, treat_turnover = probe._new_probe_state(["Nit"])

    bot_seats = [seat for seat in base_turnover.occupants]
    assert {base_turnover.archetype_for(seat) for seat in bot_seats} == {"Nit"}
    assert {treat_turnover.archetype_for(seat) for seat in bot_seats} == {"Nit"}


def test_squeeze_wider_range_default_matches_unconfirmed_v21_result():
    assert abc_bot.SQUEEZE_WIDER_RANGE is False


def test_unproven_or_harmful_ablation_rules_default_off():
    assert abc_bot.SIZE_UP_ON_TURN is False
    assert abc_bot.ISO_RAISE_OVER_LIMPERS is False
    assert abc_bot.HERO_PROGRESSIVE_POT_DAMPING is False


def test_multiway_aware_is_recomputed_from_subflags():
    original = {
        "MULTIWAY_NARROW_CALL_RANGE": abc_bot.MULTIWAY_NARROW_CALL_RANGE,
        "MULTIWAY_DISABLE_AIR_CBET": abc_bot.MULTIWAY_DISABLE_AIR_CBET,
        "MULTIWAY_DISABLE_LOOSE_CALL": abc_bot.MULTIWAY_DISABLE_LOOSE_CALL,
        "MULTIWAY_AWARE": abc_bot.MULTIWAY_AWARE,
    }
    try:
        probe._apply_flag_state(
            {
                "MULTIWAY_NARROW_CALL_RANGE": False,
                "MULTIWAY_DISABLE_AIR_CBET": True,
                "MULTIWAY_DISABLE_LOOSE_CALL": False,
            }
        )
        assert abc_bot.MULTIWAY_AWARE is True
        probe._apply_flag_state(
            {
                "MULTIWAY_NARROW_CALL_RANGE": False,
                "MULTIWAY_DISABLE_AIR_CBET": False,
                "MULTIWAY_DISABLE_LOOSE_CALL": False,
            }
        )
        assert abc_bot.MULTIWAY_AWARE is False
    finally:
        probe._restore_flags(original)
