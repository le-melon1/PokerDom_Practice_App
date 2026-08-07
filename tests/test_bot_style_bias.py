from backend.bots.behavior_clone import _style_bias


def test_style_bias_amplifies_aggression_for_loose_archetypes():
    bias = _style_bias("Maniac")
    assert bias["bets"] > bias["folds"]


def test_style_bias_reduces_aggression_for_nit():
    bias = _style_bias("Nit")
    assert bias["folds"] > bias["bets"]
