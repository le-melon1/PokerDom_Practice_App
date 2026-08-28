from collections import Counter

import backend.sessions.live_dynamics as live_dynamics
from backend.sessions.live_dynamics import ARCHETYPE_POPULATION_WEIGHTS, TableTurnover


def test_archetype_reseating_matches_real_population_mix_not_uniform(monkeypatch):
    # Isolated from NAME_FORCED_ARCHETYPE ("Den" -> TAG, see its own
    # comment in live_dynamics.py) -- that's a real, intentional skew
    # tested separately, not what this test is checking.
    monkeypatch.setattr(live_dynamics, "NAME_FORCED_ARCHETYPE", {})
    turnover = TableTurnover(bot_seats=[1], rng_seed=42)
    counts = Counter()
    for _ in range(4000):
        turnover._seat_new_occupant(1)
        counts[turnover.archetype_for(1)] += 1

    total_weight = sum(ARCHETYPE_POPULATION_WEIGHTS.values())
    for archetype, weight in ARCHETYPE_POPULATION_WEIGHTS.items():
        expected_share = weight / total_weight
        observed_share = counts[archetype] / 4000
        assert abs(observed_share - expected_share) < 0.03

    # Loose-passive (most common in the real data) must be seated far more
    # often than Maniac (rarest) -- this is the behavior a uniform
    # random.choice() over the 6 archetypes would NOT reproduce.
    assert counts["Loose-passive"] > counts["Maniac"] * 2


def test_should_leave_on_bust_or_planned_length():
    turnover = TableTurnover(bot_seats=[1], rng_seed=1)
    occ = turnover.occupants[1]
    occ.planned_length = 5
    for _ in range(4):
        turned_over = turnover.after_hand({1: 100.0}, starting_stack=100.0)
        assert turned_over[1] is False
    turned_over = turnover.after_hand({1: 100.0}, starting_stack=100.0)
    assert turned_over[1] is True  # reached planned length

    turnover2 = TableTurnover(bot_seats=[1], rng_seed=1)
    turnover2.occupants[1].planned_length = 999
    turned_over2 = turnover2.after_hand({1: 0.0}, starting_stack=100.0)
    assert turned_over2[1] is True  # busted, regardless of planned length


def test_bots_get_short_names_and_den_always_plays_tag():
    turnover = TableTurnover(bot_seats=[1, 2, 3, 4, 5], rng_seed=7)
    names = {seat: turnover.name_for(seat) for seat in (1, 2, 3, 4, 5)}
    assert len(set(names.values())) == 5  # no duplicate names at one table
    for name in names.values():
        assert 3 <= len(name) <= 4

    for seat, name in names.items():
        if name == "Den":
            assert turnover.archetype_for(seat) == "TAG"

    # Force it directly, many times, to confirm the override actually
    # fires (rng_seed above may or may not have drawn "Den" naturally).
    hits = 0
    for seed in range(100):
        t = TableTurnover(bot_seats=[1], rng_seed=seed)
        if t.name_for(1) == "Den":
            hits += 1
            assert t.archetype_for(1) == "TAG"
    assert hits > 0
