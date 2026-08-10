from backend.bots.player_profile_bots import choose_player_profile_action, load_profile_pool
from backend.engine.table import Table
from backend.sessions.live_dynamics import TableTurnover


def test_load_profile_pool_has_35_real_players_with_expected_fields():
    pool = load_profile_pool()
    assert len(pool) == 35
    for pid, profile in pool.items():
        assert pid.startswith("real_")
        assert profile["archetype"] in {"Nit", "TAG", "LAG", "Loose-passive", "Station", "Maniac"}
        assert 0.0 <= profile["vpip"] <= 1.0
        assert profile["hands_seen"] >= 500


def test_load_profile_pool_has_at_least_3_nits():
    # 20 profiles originally gave only 1 Nit (7.4% of 20 rounds down) -- user
    # asked for enough players that Nit gets a real seat count, not a token
    # one. 35 is the smallest N where proportional (largest-remainder)
    # allocation from the real population weights yields >=3.
    pool = load_profile_pool()
    nits = [pid for pid, p in pool.items() if p["archetype"] == "Nit"]
    assert len(nits) >= 3


def _heads_up_hand():
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=2)
    table.add_player(seat=1, name="Hero", stack=200.0)
    table.add_player(seat=2, name="Bot", stack=200.0)
    hand = table.start_new_hand()
    return hand


def test_choose_player_profile_action_returns_a_legal_action():
    hand = _heads_up_hand()
    seat = hand.current_actor()
    pool = load_profile_pool()
    for profile_id in list(pool.keys())[:5]:
        action, amount = choose_player_profile_action(hand, seat, profile_id, session_hands_so_far=0, seed=1)
        assert action in {"fold", "check", "call", "bet", "raise"}
        if action in {"bet", "raise"}:
            assert amount is not None and amount > 0


def test_choose_player_profile_action_is_deterministic_given_a_seed():
    hand = _heads_up_hand()
    seat = hand.current_actor()
    r1 = choose_player_profile_action(hand, seat, "real_13", session_hands_so_far=10, seed=7)
    r2 = choose_player_profile_action(hand, seat, "real_13", session_hands_so_far=10, seed=7)
    assert r1 == r2


def test_table_turnover_with_player_profile_ids_seats_only_those_profiles():
    chosen = ["real_13", "real_19"]  # a Nit and a TAG
    turnover = TableTurnover(bot_seats=[2, 3, 4, 5, 6], rng_seed=1, player_profile_ids=chosen)
    pool = load_profile_pool()
    for seat in [2, 3, 4, 5, 6]:
        pid = turnover.profile_id_for(seat)
        assert pid in chosen
        assert turnover.archetype_for(seat) == pool[pid]["archetype"]


def test_table_turnover_without_player_profile_ids_has_no_profile_id():
    turnover = TableTurnover(bot_seats=[2, 3], rng_seed=1)
    for seat in [2, 3]:
        assert turnover.profile_id_for(seat) is None
        assert turnover.archetype_for(seat) in {"Nit", "TAG", "LAG", "Loose-passive", "Station", "Maniac"}


def test_table_turnover_player_profile_occupant_tracks_hands_played_for_session_feature():
    turnover = TableTurnover(bot_seats=[2], rng_seed=1, player_profile_ids=["real_13"])
    assert turnover.occupants[2].hands_played == 0
    turnover.after_hand({2: 150.0}, starting_stack=200.0)
    assert turnover.occupants[2].hands_played == 1
