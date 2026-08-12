from scripts.simulate_abc_bot import RAKE_CAP_BB, RAKE_PERCENT, _paired_delta_stats, run_batch


def test_run_batch_is_repeatable_given_same_seed():
    first = run_batch(50, RAKE_PERCENT, RAKE_CAP_BB, seed=42, common_random=True)
    second = run_batch(50, RAKE_PERCENT, RAKE_CAP_BB, seed=42, common_random=True)

    keys = (
        "hands",
        "hero_net_bb",
        "bb_per_100",
        "bb_per_100_excl_monsters",
        "monster_pot_rate",
        "hero_vpip",
        "hero_pfr",
    )
    assert {k: first[k] for k in keys} == {k: second[k] for k in keys}


def test_paired_a_a_delta_is_exactly_zero():
    first = run_batch(50, RAKE_PERCENT, RAKE_CAP_BB, seed=42, common_random=True)
    second = run_batch(50, RAKE_PERCENT, RAKE_CAP_BB, seed=42, common_random=True)

    paired = _paired_delta_stats(first, second)

    assert paired["delta_bb100"] == 0
    assert paired["ci95_bb100"] == 0
