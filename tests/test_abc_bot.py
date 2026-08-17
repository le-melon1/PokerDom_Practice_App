import pytest

import backend.bots.abc_bot as abc_bot
from backend.bots.abc_bot import (
    _is_wet_board,
    choose_abc_action,
    has_top_pair_or_better,
    has_trips_or_better,
    has_very_strong_hand,
    should_call_with_draw,
)
from backend.engine.hand import Hand
from backend.engine.models import Player


def make_players(n, stack=200.0):
    return [Player(seat=i + 1, name=f"P{i+1}", stack=stack) for i in range(n)]


def _cards_from_notation(notation: str) -> list[str]:
    if len(notation) == 2:  # pocket pair, e.g. "99"
        r = notation[0]
        return [f"{r}c", f"{r}d"]
    r1, r2, suited = notation[0], notation[1], notation[2] == "s"
    return [f"{r1}c", f"{r2}c"] if suited else [f"{r1}c", f"{r2}d"]


def test_isolates_a_limper_with_a_wider_range_when_flag_on():
    open_ranges, _, steal_ranges, *_ = abc_bot._ranges()
    position = "BTN"
    extra_hands = steal_ranges[position] - open_ranges[position]
    assert extra_hands, "expected the widened range to be strictly bigger than the plain open range for BTN"
    test_hand = next(iter(extra_hands))

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "call")  # UTG limps
    for s in (5, 6):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    actor = hand.current_actor()  # seat 1, BTN
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)
    original_tight_iso = abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS
    abc_bot.ISO_WIDER_RANGE_OVER_LIMPERS = True
    abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS = False
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.ISO_WIDER_RANGE_OVER_LIMPERS = False
        abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS = original_tight_iso
    assert action == "raise"


def test_does_not_isolate_a_limper_wider_when_flag_off():
    open_ranges, _, steal_ranges, *_ = abc_bot._ranges()
    position = "BTN"
    extra_hands = steal_ranges[position] - open_ranges[position]
    test_hand = next(iter(extra_hands))

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "call")  # UTG limps
    for s in (5, 6):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    actor = hand.current_actor()
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)
    # ISO_WIDER_RANGE_OVER_LIMPERS defaults False -- a hand outside the
    # plain open range still folds even facing a limper.
    original_tight_iso = abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS
    abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS = False
    try:
        action, _ = choose_abc_action(hand, actor)
        assert action == "fold"
    finally:
        abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS = original_tight_iso


def test_iso_wider_range_does_not_fire_into_an_unopened_pot_with_no_limpers():
    open_ranges, _, steal_ranges, *_ = abc_bot._ranges()
    position = "UTG"
    extra_hands = steal_ranges[position] - open_ranges[position]
    test_hand = next(iter(extra_hands))

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    actor = hand.current_actor()  # UTG, first to act -- no limpers yet
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)
    abc_bot.ISO_WIDER_RANGE_OVER_LIMPERS = True
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.ISO_WIDER_RANGE_OVER_LIMPERS = False
    assert action == "fold"


def test_tight_big_iso_folds_plain_open_hands_outside_tight_iso_range():
    open_ranges, _, _, tight_iso_ranges, *_, limp_behind_ranges, _ = abc_bot._ranges()
    position = "BTN"
    # Exclude LIMP_BEHIND_OVER_LIMPERS's own hand set (confirmed True since
    # 2026-08-12/16) -- A2s/A3s/etc. are deliberately NOT meant to fold here,
    # they're meant to limp behind instead, a different (correct) rule this
    # test isn't trying to cover. sorted()+[0], not next(iter(...)), so the
    # picked hand doesn't depend on Python's per-process hash-seed-randomized
    # set iteration order (this test intermittently picked A2s/A3s and failed
    # on the "call" a limp-behind produces, depending on PYTHONHASHSEED).
    marginal_iso_hands = open_ranges[position] - tight_iso_ranges[position] - limp_behind_ranges.get(position, set())
    assert marginal_iso_hands, "expected tight iso range to be narrower than the plain open range"
    test_hand = sorted(marginal_iso_hands)[0]

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "call")  # UTG limps
    for s in (5, 6):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    actor = hand.current_actor()
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)
    original_tight_iso = abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS
    abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS = True
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS = original_tight_iso
    assert action == "fold"


def test_tight_big_iso_raises_bigger_with_tight_iso_hand():
    _, _, _, tight_iso_ranges, *_ = abc_bot._ranges()
    position = "BTN"
    # picked deterministically and excluding VALUE_3BET_TIGHT so this test
    # isn't sensitive to SIZE_UP_PREMIUM_OPENS's extra sizing bonus (which
    # only applies to premium hands) or to set-iteration hash randomization
    test_hand = next(h for h in sorted(tight_iso_ranges[position]) if h not in abc_bot.VALUE_3BET_TIGHT)

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "call")  # UTG limps
    for s in (5, 6):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    actor = hand.current_actor()
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)
    original_tight_iso = abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS
    abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS = True
    try:
        action, amount = choose_abc_action(hand, actor)
    finally:
        abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS = original_tight_iso
    assert action == "raise"
    assert amount == pytest.approx(14.0)  # (5.5bb base + 1.5bb for one limper) * 2-chip BB


def test_utg_opens_a_premium_hand():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    actor = hand.current_actor()  # seat 4, UTG
    hand.players[actor].hole_cards = ["As", "Ah"]
    action, amount = choose_abc_action(hand, actor)
    assert action == "raise"
    # v19/r20: SIZE_UP_PREMIUM_OPENS shipped True 2026-08-13 (confirmed via
    # chance-enumeration, see abc_bot.py changelog) -- AA gets the standard
    # 2.5bb open plus the 1.5bb premium bonus.
    assert amount == 8.0


def test_utg_folds_a_trash_hand():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    actor = hand.current_actor()
    hand.players[actor].hole_cards = ["7c", "2d"]
    action, amount = choose_abc_action(hand, actor)
    assert action == "fold"


def test_bb_checks_when_everyone_folds_to_it():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    for seat in (4, 5, 6, 1, 2):
        hand.apply_action(seat, "fold")
    bb_seat = hand.current_actor()
    hand.players[bb_seat].hole_cards = ["7c", "2d"]
    action, amount = choose_abc_action(hand, bb_seat)
    assert action == "check"


def test_folds_to_a_raise_with_a_weak_hand_outside_position_range():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG opens
    actor = hand.current_actor()  # seat 5, MP
    hand.players[actor].hole_cards = ["9c", "4d"]
    action, amount = choose_abc_action(hand, actor)
    assert action == "fold"


def test_calls_a_raise_with_a_hand_in_the_narrow_call_range_but_not_premium():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    actor = hand.current_actor()
    hand.players[actor].hole_cards = ["Jd", "Td"]  # JTs -- in the call range, not in VALUE_3BET -- calls
    action, amount = choose_abc_action(hand, actor)
    assert action == "call"


def test_calls_wider_vs_a_min_raise_when_flag_on():
    _, call_ranges, _, _, call_ranges_wide, _, *_ = abc_bot._ranges()
    position = "MP"
    wide_only = call_ranges_wide[position] - call_ranges[position]
    assert wide_only, "expected the wide call tier to be strictly bigger than the standard one for MP"
    test_hand = next(iter(wide_only))

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=4.0)  # UTG min-raises to 2bb -- a "small" raise
    actor = hand.current_actor()  # MP
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)
    abc_bot.SIZE_SCALED_CALL_RANGE = True
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.SIZE_SCALED_CALL_RANGE = False
    assert action == "call"


def test_does_not_call_wider_vs_a_min_raise_when_flag_off():
    _, call_ranges, _, _, call_ranges_wide, _, *_ = abc_bot._ranges()
    position = "MP"
    wide_only = call_ranges_wide[position] - call_ranges[position]
    test_hand = next(iter(wide_only))

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=4.0)
    actor = hand.current_actor()
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)
    # SIZE_SCALED_CALL_RANGE defaults False -- the standard range applies
    # regardless of how small the raise actually was.
    action, _ = choose_abc_action(hand, actor)
    assert action == "fold"


def test_folds_a_standard_call_range_hand_to_a_big_raise_when_flag_on():
    _, call_ranges, _, _, _, call_ranges_narrow, *_ = abc_bot._ranges()
    position = "MP"
    narrowed_out = call_ranges[position] - call_ranges_narrow[position] - abc_bot.VALUE_3BET - abc_bot.BLUFF_3BET_RANGE
    assert narrowed_out, "expected the narrow call tier to exclude some hands the standard one includes, for MP"
    test_hand = sorted(narrowed_out)[0]

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=10.0)  # UTG raises big -- 5bb, a "big" raise
    actor = hand.current_actor()
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)
    abc_bot.SIZE_SCALED_CALL_RANGE = True
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.SIZE_SCALED_CALL_RANGE = False
    assert action == "fold"


def test_still_calls_a_standard_sized_raise_with_the_standard_range_when_flag_on():
    # A raise strictly between the two thresholds (SMALL/BIG_RAISE_BB_
    # THRESHOLD, 2.5/3.0bb -- recalibrated 2026-08-12 to bracket this
    # population's real ~2.35bb/~3.25bb sizing clusters, see the constants'
    # comment) uses the plain standard call range, same as the flag off.
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.5)  # 2.75bb -- strictly inside the dead zone
    actor = hand.current_actor()
    hand.players[actor].hole_cards = ["Jd", "Td"]  # JTs -- in the standard call range
    abc_bot.SIZE_SCALED_CALL_RANGE = True
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.SIZE_SCALED_CALL_RANGE = False
    assert action == "call"


def test_bluff_3bets_a_speculative_hand_vs_a_known_nit_raiser_when_flag_on():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG (seat 4) opens
    actor = hand.current_actor()
    hand.players[actor].hole_cards = ["Jd", "Td"]  # JTs -- in BLUFF_3BET_RANGE, not VALUE_3BET
    original = abc_bot.BLUFF_3BET_VS_TIGHT
    abc_bot.BLUFF_3BET_VS_TIGHT = True
    try:
        action, amount = choose_abc_action(hand, actor, opponent_archetypes={4: "Nit"})
    finally:
        abc_bot.BLUFF_3BET_VS_TIGHT = original
    assert action == "raise"
    assert amount == 15.0  # 3x the 5bb open, same sizing as a value 3-bet


def test_does_not_bluff_3bet_vs_a_known_loose_raiser_even_when_flag_on():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    actor = hand.current_actor()
    hand.players[actor].hole_cards = ["Jd", "Td"]  # JTs -- same hand
    original = abc_bot.BLUFF_3BET_VS_TIGHT
    abc_bot.BLUFF_3BET_VS_TIGHT = True
    try:
        # Station is not in TIGHT_ARCHETYPES_FOR_DONK_BLUFF -- falls through
        # to the normal call range instead of bluff-3-betting.
        action, amount = choose_abc_action(hand, actor, opponent_archetypes={4: "Station"})
    finally:
        abc_bot.BLUFF_3BET_VS_TIGHT = original
    assert action == "call"


def test_bluff_3bet_target_set_can_exclude_lag_without_changing_donk_bluff_targets():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    actor = hand.current_actor()
    hand.players[actor].hole_cards = ["Jd", "Td"]

    original_targets = set(abc_bot.BLUFF_3BET_TARGET_ARCHETYPES)
    original_flag = abc_bot.BLUFF_3BET_VS_TIGHT
    abc_bot.BLUFF_3BET_VS_TIGHT = True
    abc_bot.BLUFF_3BET_TARGET_ARCHETYPES = {"Nit", "TAG"}
    try:
        action, _ = choose_abc_action(hand, actor, opponent_archetypes={4: "LAG"})
    finally:
        abc_bot.BLUFF_3BET_VS_TIGHT = original_flag
        abc_bot.BLUFF_3BET_TARGET_ARCHETYPES = original_targets

    assert "LAG" in abc_bot.TIGHT_ARCHETYPES_FOR_DONK_BLUFF
    assert action == "call"


def test_bluff_3bet_defaults_on_after_large_confirmatory_run():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    actor = hand.current_actor()
    hand.players[actor].hole_cards = ["Jd", "Td"]

    action, amount = choose_abc_action(hand, actor, opponent_archetypes={4: "Nit"})
    assert abc_bot.BLUFF_3BET_VS_TIGHT is True
    assert action == "raise"
    assert amount == 15.0


def test_value_3bets_a_premium_hand_facing_a_single_raise_instead_of_flatting():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    actor = hand.current_actor()
    hand.players[actor].hole_cards = ["As", "Ah"]  # AA -- in VALUE_3BET, must raise not call
    action, amount = choose_abc_action(hand, actor)
    assert action == "raise"
    assert amount == 15.0  # 3x the 5bb open


def test_only_premium_continues_vs_a_3bet():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    hand.apply_action(5, "raise", amount=15.0)  # a 3-bet
    while hand.current_actor() != 4:
        hand.apply_action(hand.current_actor(), "fold")
    hand.players[4].hole_cards = ["Jd", "Js"]  # JJ -- not in the premium-vs-3bet set
    action, _ = choose_abc_action(hand, 4)
    assert action == "fold"
    hand.players[4].hole_cards = ["Qd", "Qs"]  # QQ -- is in the premium set
    # SHOVE_AA_KK_VS_3BET_PLUS defaults True and now includes QQ (2026-08-16),
    # so isolate it to keep testing the plain premium-continues call path.
    abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = False
    try:
        action, _ = choose_abc_action(hand, 4)
    finally:
        abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = True
    assert action == "call"


def test_aa_kk_shove_vs_3bet_plus_when_flag_on():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    hand.apply_action(5, "raise", amount=15.0)
    while hand.current_actor() != 4:
        hand.apply_action(hand.current_actor(), "fold")
    hand.players[4].hole_cards = ["As", "Ah"]

    original = abc_bot.SHOVE_AA_KK_VS_3BET_PLUS
    abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = True
    try:
        action, amount = choose_abc_action(hand, 4)
    finally:
        abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = original

    assert action == "raise"
    assert amount == hand.legal_actions(4)["max_raise_to"]


def test_aa_kk_shove_flag_does_not_shove_qq_with_the_narrow_range():
    # QQ is in the shipped-default range now (2026-08-16) -- this test
    # verifies the range gate itself, not the default: with the ORIGINAL
    # narrow {AA,KK} range explicitly set, QQ must still fall through to a
    # plain call rather than shoving.
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    hand.apply_action(5, "raise", amount=15.0)
    while hand.current_actor() != 4:
        hand.apply_action(hand.current_actor(), "fold")
    hand.players[4].hole_cards = ["Qd", "Qs"]

    original_flag = abc_bot.SHOVE_AA_KK_VS_3BET_PLUS
    original_range = set(abc_bot.SHOVE_VS_3BET_PLUS_RANGE)
    abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = True
    abc_bot.SHOVE_VS_3BET_PLUS_RANGE = {"AA", "KK"}
    try:
        action, amount = choose_abc_action(hand, 4)
    finally:
        abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = original_flag
        abc_bot.SHOVE_VS_3BET_PLUS_RANGE = original_range

    assert action == "call"
    assert amount is None


def test_shove_vs_3bet_plus_range_can_include_qq():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    hand.apply_action(5, "raise", amount=15.0)
    while hand.current_actor() != 4:
        hand.apply_action(hand.current_actor(), "fold")
    hand.players[4].hole_cards = ["Qd", "Qs"]

    original_flag = abc_bot.SHOVE_AA_KK_VS_3BET_PLUS
    original_range = set(abc_bot.SHOVE_VS_3BET_PLUS_RANGE)
    abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = True
    abc_bot.SHOVE_VS_3BET_PLUS_RANGE = {"AA", "KK", "QQ"}
    try:
        action, amount = choose_abc_action(hand, 4)
    finally:
        abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = original_flag
        abc_bot.SHOVE_VS_3BET_PLUS_RANGE = original_range

    assert action == "raise"
    assert amount == hand.legal_actions(4)["max_raise_to"]


def test_aa_kk_shove_flag_defaults_on():
    # Shipped True 2026-08-16 (r18v, widened to QQ/AKs/AKo too -- confirmed
    # positive both seeds, see abc_bot.py's changelog).
    assert abc_bot.SHOVE_AA_KK_VS_3BET_PLUS is True
    assert abc_bot.SHOVE_VS_3BET_PLUS_RANGE == {"AA", "KK", "QQ", "AKs", "AKo"}


def _facing_a_near_shove_4bet(stack=40.0):
    players = make_players(6, stack=stack)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG opens to 5bb
    hand.apply_action(5, "raise", amount=35.0)  # 3-bet to 35bb -- most of a 40bb stack
    while hand.current_actor() != 4:
        hand.apply_action(hand.current_actor(), "fold")
    return hand  # hero (seat 4) faces to_call=30 out of a 35bb remaining stack (~86%)


# 2026-08-16: SHOVE_AA_KK_VS_3BET_PLUS shipped True with its range widened to
# {AA,KK,QQ,AKs,AKo} -- exactly FOLDABLE_PREMIUM_VS_EXTREME_AGGRO's hand set,
# and it's checked BEFORE FOLD_PREMIUM_VS_EXTREME_AGGRO in choose_abc_action,
# so by default those hands now always shove facing 3bet+ and never reach the
# fold-vs-extreme-aggro branch at all (that branch is still False/untested on
# its own, but is now structurally dead for its whole target range unless a
# future session narrows the shove range back down). These tests disable the
# shove flag explicitly so they keep testing FOLD_PREMIUM_VS_EXTREME_AGGRO in
# isolation, as originally intended.


def test_folds_qq_to_an_extreme_4bet_from_a_known_nit_when_flag_on():
    hand = _facing_a_near_shove_4bet()
    hand.players[4].hole_cards = ["Qd", "Qs"]
    abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = False
    abc_bot.FOLD_PREMIUM_VS_EXTREME_AGGRO = True
    try:
        action, _ = choose_abc_action(hand, 4, opponent_archetypes={5: "Nit"})
    finally:
        abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = True
        abc_bot.FOLD_PREMIUM_VS_EXTREME_AGGRO = False
    assert action == "fold"


def test_never_folds_aa_even_to_an_extreme_4bet_from_a_known_nit():
    hand = _facing_a_near_shove_4bet()
    hand.players[4].hole_cards = ["As", "Ah"]
    abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = False
    abc_bot.FOLD_PREMIUM_VS_EXTREME_AGGRO = True
    try:
        action, _ = choose_abc_action(hand, 4, opponent_archetypes={5: "Nit"})
    finally:
        abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = True
        abc_bot.FOLD_PREMIUM_VS_EXTREME_AGGRO = False
    assert action == "call"


def test_does_not_fold_qq_to_an_extreme_4bet_from_a_known_loose_raiser():
    hand = _facing_a_near_shove_4bet()
    hand.players[4].hole_cards = ["Qd", "Qs"]
    abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = False
    abc_bot.FOLD_PREMIUM_VS_EXTREME_AGGRO = True
    try:
        # Maniac isn't in TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD -- a Maniac's
        # shove range is nowhere near pure premium, so QQ keeps calling.
        action, _ = choose_abc_action(hand, 4, opponent_archetypes={5: "Maniac"})
    finally:
        abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = True
        abc_bot.FOLD_PREMIUM_VS_EXTREME_AGGRO = False
    assert action == "call"


def test_extreme_4bet_fold_flag_off_by_default_still_calls_qq():
    hand = _facing_a_near_shove_4bet()
    hand.players[4].hole_cards = ["Qd", "Qs"]
    # FOLD_PREMIUM_VS_EXTREME_AGGRO defaults False -- baseline behavior.
    # SHOVE_AA_KK_VS_3BET_PLUS defaults True now, so isolate it too.
    abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = False
    try:
        action, _ = choose_abc_action(hand, 4, opponent_archetypes={5: "Nit"})
    finally:
        abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = True
    assert action == "call"


def test_does_not_fold_qq_to_a_modest_sized_3bet_even_vs_a_known_nit():
    # Same opponent, same hand, but the 3-bet is a normal ~3x size, not an
    # extreme one -- to_call is nowhere near 50% of hero's stack, so the
    # extreme-aggression gate never engages even with the flag on.
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    hand.apply_action(5, "raise", amount=15.0)  # a normal 3-bet, not a shove
    while hand.current_actor() != 4:
        hand.apply_action(hand.current_actor(), "fold")
    hand.players[4].hole_cards = ["Qd", "Qs"]
    abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = False
    abc_bot.FOLD_PREMIUM_VS_EXTREME_AGGRO = True
    try:
        action, _ = choose_abc_action(hand, 4, opponent_archetypes={5: "Nit"})
    finally:
        abc_bot.SHOVE_AA_KK_VS_3BET_PLUS = True
        abc_bot.FOLD_PREMIUM_VS_EXTREME_AGGRO = False
    assert action == "call"


def test_limp_behind_calls_speculative_hands_when_candidate_on():
    open_ranges = abc_bot._ranges()[0]
    limp_ranges = abc_bot._ranges()[6]
    tight_iso_ranges = abc_bot._ranges()[3]
    position = "BTN"
    limp_only = limp_ranges[position] - tight_iso_ranges[position] - open_ranges[position]
    assert limp_only
    test_hand = sorted(limp_only)[0]

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "call")
    for s in (5, 6):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    actor = hand.current_actor()
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)

    original = abc_bot.LIMP_BEHIND_OVER_LIMPERS
    abc_bot.LIMP_BEHIND_OVER_LIMPERS = True
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.LIMP_BEHIND_OVER_LIMPERS = original

    assert action == "call"


def test_position_aware_call_tightens_vs_utg_open():
    _, call_ranges, _, _, _, call_ranges_narrow, *_ = abc_bot._ranges()
    narrowed_out = call_ranges["MP"] - call_ranges_narrow["MP"] - abc_bot.VALUE_3BET - abc_bot.BLUFF_3BET_RANGE
    assert narrowed_out
    test_hand = sorted(narrowed_out)[0]

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG opens
    actor = hand.current_actor()  # MP
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)

    original = abc_bot.CALL_RANGE_BY_RAISER_POSITION
    abc_bot.CALL_RANGE_BY_RAISER_POSITION = True
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.CALL_RANGE_BY_RAISER_POSITION = original

    assert action == "fold"


def test_position_aware_call_widens_vs_late_open():
    _, call_ranges, _, _, call_ranges_wide, _, *_ = abc_bot._ranges()
    wide_only = call_ranges_wide["BTN"] - call_ranges["BTN"] - abc_bot.VALUE_3BET - abc_bot.BLUFF_3BET_RANGE
    assert wide_only
    test_hand = sorted(wide_only)[0]

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "fold")
    hand.apply_action(5, "fold")
    hand.apply_action(6, "raise", amount=5.0)  # CO opens
    actor = hand.current_actor()  # BTN
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)

    original = abc_bot.CALL_RANGE_BY_RAISER_POSITION
    abc_bot.CALL_RANGE_BY_RAISER_POSITION = True
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.CALL_RANGE_BY_RAISER_POSITION = original

    assert action == "call"


def test_bb_defends_wider_vs_late_minraise_when_candidate_on():
    bb_defend_ranges = abc_bot._ranges()[7]
    defend_only = bb_defend_ranges["BB"] - abc_bot.VALUE_3BET - abc_bot.BLUFF_3BET_RANGE
    assert defend_only
    test_hand = sorted(defend_only)[0]

    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    for seat in (4, 5, 6):
        hand.apply_action(seat, "fold")
    hand.apply_action(1, "raise", amount=4.0)  # BTN min-raises to 2bb
    hand.apply_action(2, "fold")
    actor = hand.current_actor()
    assert actor == 3
    hand.players[actor].hole_cards = _cards_from_notation(test_hand)

    original = abc_bot.BB_DEFEND_VS_STEAL_MINRAISE
    abc_bot.BB_DEFEND_VS_STEAL_MINRAISE = True
    try:
        action, _ = choose_abc_action(hand, actor)
    finally:
        abc_bot.BB_DEFEND_VS_STEAL_MINRAISE = original

    assert action == "call"


def _reach_river_checked_to_with_trips():
    # Jumps straight to a small-pot river spot with trips instead of
    # replaying a full flop/turn action sequence -- choose_abc_action only
    # reads street/board/hole_cards/contributed amounts for this decision,
    # not the intervening action history. Keeps the pot at preflop-only
    # size (10, i.e. pot_bb=5.0, right at HERO_POT_DAMPING_START_BB), so
    # hero_damp ~ 0 and the overbet sizing isn't swamped by the monster-pot
    # damping mechanism -- a real, disclosed interaction (see RIVER_
    # OVERBET_NUTS_VS_LOOSE's comment) that DOES neuter this in a bigger
    # pot, and initially did before this helper was rewritten.
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG (seat 4) opens
    for s in (5, 6, 1, 2):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    hand.apply_action(3, "call")  # BB calls -- pot is now 10 (5+5)
    assert hand.street == "flop"
    hand.street_idx = 3  # jump straight to river
    hand.current_bet = 0.0
    for p in hand.players.values():
        p.street_contributed = 0.0
    hand.board = ["9c", "9d", "2h", "5c", "7d"]  # board pair of 9s
    hand.players[4].hole_cards = ["9s", "Kd"]  # hero's third 9 -- trips
    return hand


def test_overbets_river_trips_vs_a_known_station_when_flag_on():
    hand = _reach_river_checked_to_with_trips()
    pot_before = sum(p.total_contributed for p in hand.players.values())
    abc_bot.RIVER_OVERBET_NUTS_VS_LOOSE = True
    try:
        action, amount = choose_abc_action(hand, 4, opponent_archetypes={3: "Station"})
    finally:
        abc_bot.RIVER_OVERBET_NUTS_VS_LOOSE = False
    assert action == "bet"
    assert amount >= pot_before  # a genuine overbet, not just a bigger-than-standard bet


def test_does_not_overbet_river_vs_a_known_tight_opponent_even_when_flag_on():
    hand = _reach_river_checked_to_with_trips()
    pot_before = sum(p.total_contributed for p in hand.players.values())
    abc_bot.RIVER_OVERBET_NUTS_VS_LOOSE = True
    try:
        # Nit isn't in LOOSE_ARCHETYPES -- no reason to think a Nit pays off
        # an overbet any better than a standard one, so no special sizing.
        action, amount = choose_abc_action(hand, 4, opponent_archetypes={3: "Nit"})
    finally:
        abc_bot.RIVER_OVERBET_NUTS_VS_LOOSE = False
    assert action == "bet"
    assert amount < pot_before


def test_river_overbet_flag_off_by_default_uses_standard_sizing():
    hand = _reach_river_checked_to_with_trips()
    pot_before = sum(p.total_contributed for p in hand.players.values())
    # RIVER_OVERBET_NUTS_VS_LOOSE defaults False -- baseline sizing tiers.
    action, amount = choose_abc_action(hand, 4, opponent_archetypes={3: "Station"})
    assert action == "bet"
    assert amount < pot_before


def test_top_pair_or_better_detection():
    assert has_top_pair_or_better(["Ah", "Kd"], ["Ac", "7d", "2s"])  # top pair aces
    assert has_top_pair_or_better(["Ah", "Kd"], ["Ac", "Kd", "2s"])  # two pair (dup card ignored in this synthetic test)
    assert not has_top_pair_or_better(["Ah", "Kd"], ["9c", "7d", "2s"])  # ace-king high, no pair
    assert not has_top_pair_or_better(["9h", "9d"], ["Ac", "7d", "2s"])  # underpair -- NOT top pair or overpair
    assert has_top_pair_or_better(["9h", "9d"], ["8c", "7d", "2s"])  # overpair to this board


def _reach_turn_with_initiative(hero_hole):
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG (seat 4) opens and will have initiative
    for s in (5, 6, 1, 2):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    hand.apply_action(3, "call")  # BB calls
    assert hand.street == "flop"

    hand.board = ["9c", "5d", "2h"]  # controlled flop -- irrelevant to hero's pocket-pair overpair scenario below
    hand.apply_action(3, "check")  # BB acts first postflop
    hand.players[4].hole_cards = hero_hole
    action, amount = choose_abc_action(hand, 4)
    assert action == "bet"

    hand.apply_action(4, "bet", amount=amount)
    hand.apply_action(3, "call")
    assert hand.street == "turn"
    hand.board = ["9c", "5d", "2h", "8s"]  # controlled turn card, keeps hero's hand category unambiguous
    hand.apply_action(3, "check")  # BB acts first postflop again
    return hand


def _reach_turn_with_initiative_air_and_scare_card():
    # Same shape as _reach_turn_with_initiative, but hero's hand never
    # pairs anything (air the whole way) and the turn card (Ah) is a fresh
    # overcard to the 9-5-2 flop -- a real scare card by _is_scare_card.
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    for s in (5, 6, 1, 2):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    hand.apply_action(3, "call")
    assert hand.street == "flop"
    hand.board = ["9c", "5d", "2h"]
    hand.apply_action(3, "check")
    hand.players[4].hole_cards = ["Kc", "Qd"]  # king/queen high -- no pair anywhere on this run-out
    action, amount = choose_abc_action(hand, 4, opponent_archetypes={3: "Nit"})
    assert action == "bet"  # flop cbet with air
    hand.apply_action(4, "bet", amount=amount)
    hand.apply_action(3, "call")
    assert hand.street == "turn"
    hand.board = ["9c", "5d", "2h", "Ah"]  # fresh overcard -- a real scare card
    hand.apply_action(3, "check")
    return hand


def test_barrel_bluffs_a_scare_card_vs_a_known_nit_when_flag_on():
    hand = _reach_turn_with_initiative_air_and_scare_card()
    abc_bot.BARREL_BLUFF_VS_TIGHT = True
    try:
        action, amount = choose_abc_action(hand, 4, opponent_archetypes={3: "Nit"})
    finally:
        abc_bot.BARREL_BLUFF_VS_TIGHT = False
    assert action == "bet"
    assert amount > 0


def test_does_not_barrel_bluff_vs_a_known_loose_opponent_even_when_flag_on():
    hand = _reach_turn_with_initiative_air_and_scare_card()
    abc_bot.BARREL_BLUFF_VS_TIGHT = True
    try:
        # Station is not in TIGHT_ARCHETYPES_FOR_DONK_BLUFF -- no story to
        # tell against a player who doesn't fold more to continued
        # aggression, so hero just gives up with air.
        action, _ = choose_abc_action(hand, 4, opponent_archetypes={3: "Station"})
    finally:
        abc_bot.BARREL_BLUFF_VS_TIGHT = False
    assert action == "check"


def test_barrel_bluff_flag_off_by_default_checks_back_air_vs_nit():
    hand = _reach_turn_with_initiative_air_and_scare_card()
    # BARREL_BLUFF_VS_TIGHT defaults False -- baseline behavior (check back
    # with air) even facing a known Nit and a real scare card.
    action, _ = choose_abc_action(hand, 4, opponent_archetypes={3: "Nit"})
    assert action == "check"


def test_is_scare_card_detects_a_fresh_overcard_and_a_new_flush_possibility():
    hand = Hand(make_players(2), button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.street_idx = 2  # "turn"
    hand.board = ["9c", "5d", "2h", "Ah"]
    assert abc_bot._is_scare_card(hand)  # Ace outranks everything on the flop

    hand.board = ["9c", "5d", "2h", "8s"]  # 4th suit -- no card repeats a flop suit
    assert not abc_bot._is_scare_card(hand)  # 8 isn't an overcard, and no suit reaches count 2

    hand.board = ["9c", "5d", "2h", "8c"]  # rainbow flop, turn brings a SECOND club
    assert abc_bot._is_scare_card(hand)  # board just became two-tone -- a real new flush draw

    hand.street_idx = 3  # "river"
    # Board already two-tone (two clubs) before the river; the river card
    # (3h) doesn't outrank anything (9 is still the board's high card) and
    # doesn't cross into a NEW texture category (still just two-tone).
    hand.board = ["9c", "5d", "2c", "8h", "3h"]
    assert not abc_bot._is_scare_card(hand)


def _hand_with_pot(pot_bb: float) -> Hand:
    hand = Hand(make_players(2), button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.players[1].total_contributed = pot_bb / 2
    hand.players[2].total_contributed = pot_bb / 2
    hand.street_idx = 3  # river -- arbitrary, _optimal_value_sizing doesn't gate on street itself
    return hand


def test_optimal_value_sizing_picks_the_bigger_size_when_fold_pct_rises_with_size(monkeypatch):
    hand = _hand_with_pot(10.0)

    def fake_fold_pct(street, pot_fraction, archetype):
        return 0.6 if pot_fraction >= abc_bot.BIG_VALUE_SIZING_POT_FRACTION else 0.3

    monkeypatch.setattr(abc_bot, "_facing_bet_fold_pct", fake_fold_pct)
    assert abc_bot._optimal_value_sizing(hand, "TestArchetype") == abc_bot.BIG_VALUE_SIZING_POT_FRACTION


def test_optimal_value_sizing_picks_the_smaller_size_when_fold_pct_falls_with_size(monkeypatch):
    hand = _hand_with_pot(10.0)

    def fake_fold_pct(street, pot_fraction, archetype):
        return 0.3 if pot_fraction >= abc_bot.BIG_VALUE_SIZING_POT_FRACTION else 0.6

    monkeypatch.setattr(abc_bot, "_facing_bet_fold_pct", fake_fold_pct)
    assert abc_bot._optimal_value_sizing(hand, "TestArchetype") == abc_bot.STANDARD_SIZING_POT_FRACTION


def test_optimal_value_sizing_returns_none_without_real_data(monkeypatch):
    hand = _hand_with_pot(10.0)
    monkeypatch.setattr(abc_bot, "_facing_bet_fold_pct", lambda street, pot_fraction, archetype: None)
    assert abc_bot._optimal_value_sizing(hand, "NoDataArchetype") is None


def test_facing_bet_fold_pct_loads_real_data_for_a_known_archetype():
    # Sanity check against the real reference table (not mocked) -- Nit is
    # a known-tight archetype with a large real sample at every street/
    # bucket, per this file's own v14 changelog notes.
    fold_pct = abc_bot._facing_bet_fold_pct("river", 0.9, "Nit")
    assert fold_pct is not None
    assert 0.0 < fold_pct < 1.0


def test_optimal_value_sizing_overrides_the_hardcoded_a2_choice_when_flag_on(monkeypatch):
    hand = _reach_river_checked_to_with_trips()  # small pot, made hand (trips), checked to

    def fake_fold_pct(street, pot_fraction, archetype):
        # Maniac isn't in SIZING_TARGET_ARCHETYPES (A2 would leave it at
        # STANDARD_SIZING_POT_FRACTION) -- but real fold data here says
        # bigger buys real extra folds for THIS specific Maniac, so v28
        # should override A2's hardcoded miss and size up anyway.
        return 0.6 if pot_fraction >= abc_bot.BIG_VALUE_SIZING_POT_FRACTION else 0.3

    monkeypatch.setattr(abc_bot, "_facing_bet_fold_pct", fake_fold_pct)
    pot_before = sum(p.total_contributed for p in hand.players.values())
    abc_bot.OPTIMAL_VALUE_SIZING_PER_ARCHETYPE = True
    # Disabled just so the expected amount below is an exact, readable
    # formula -- HERO_PROGRESSIVE_POT_DAMPING is a real, separate, already-
    # tested mechanism (not what this test is checking) that would
    # otherwise shave a few percent off the raw sizing here too (pot_bb
    # ends up just above HERO_POT_DAMPING_START_BB once the folded SB's
    # dead blind is counted).
    old_damping = abc_bot.HERO_PROGRESSIVE_POT_DAMPING
    abc_bot.HERO_PROGRESSIVE_POT_DAMPING = False
    try:
        action, amount = choose_abc_action(hand, 4, opponent_archetypes={3: "Maniac"})
    finally:
        abc_bot.OPTIMAL_VALUE_SIZING_PER_ARCHETYPE = False
        abc_bot.HERO_PROGRESSIVE_POT_DAMPING = old_damping
    assert action == "bet"
    assert amount == pytest.approx(pot_before * abc_bot.BIG_VALUE_SIZING_POT_FRACTION)


def test_cbets_flop_then_keeps_betting_the_turn_for_value_with_a_strong_hand():
    hand = _reach_turn_with_initiative(["Kc", "Kd"])  # overpair to this board -- still top-pair-or-better
    action, amount = choose_abc_action(hand, 4)
    assert action == "bet"
    assert amount > 0


def test_cbets_flop_then_checks_turn_without_barreling_a_missed_hand():
    hand = _reach_turn_with_initiative(["Ac", "Qd"]) # ace/queen high on this board -- no pair anywhere
    action, amount = choose_abc_action(hand, 4)
    assert action == "check"  # no auto-barrel with nothing


def _bb_free_flop():
    # UTG limps (calls the BB, doesn't raise), everyone else folds, BB checks
    # its option -- a genuine free flop with no preflop raise, BB has no
    # initiative but does have a live opponent (UTG) to bet into.
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "call")  # UTG limps
    for s in (5, 6, 1, 2):
        hand.apply_action(s, "fold")
    bb_seat = hand.current_actor()  # seat 3, BB
    hand.apply_action(bb_seat, "check")
    assert hand.street == "flop"
    return hand, bb_seat


def test_bets_for_value_without_initiative_a_free_flop_in_the_blinds():
    hand, bb_seat = _bb_free_flop()
    hand.board = ["9c", "9d", "2h"]
    hand.players[bb_seat].hole_cards = ["9s", "4d"]  # flopped trip nines
    action, amount = choose_abc_action(hand, bb_seat)
    assert action == "bet"
    assert amount > 0


def test_checks_without_initiative_on_a_free_flop_with_no_hand():
    hand, bb_seat = _bb_free_flop()
    hand.board = ["9c", "6d", "2h"]
    hand.players[bb_seat].hole_cards = ["Ks", "4d"]  # complete miss
    action, amount = choose_abc_action(hand, bb_seat)
    assert action == "check"


def test_made_straight_and_flush_count_as_top_pair_or_better():
    assert has_top_pair_or_better(["Jd", "Td"], ["9d", "8d", "2d"])  # made flush
    assert has_top_pair_or_better(["9c", "8c"], ["7d", "6h", "5s", "2c"])  # made straight (9-8-7-6-5), no pair
    assert not has_top_pair_or_better(["Kc", "Qh"], ["9d", "6h", "2s"])  # no made hand at all


def test_calls_a_flop_bet_with_a_flush_draw_at_the_right_price():
    # 4 to a flush, cheap price relative to the flop's ~35% rough draw equity
    assert should_call_with_draw(["Ad", "Kd"], ["9d", "6d", "2h"], "flop", to_call=5.0, pot_before=50.0)


def test_folds_a_flop_flush_draw_facing_too_steep_a_price():
    # same draw, but the bet is too big relative to the pot for the draw's equity
    assert not should_call_with_draw(["Ad", "Kd"], ["9d", "6d", "2h"], "flop", to_call=40.0, pot_before=10.0)


def test_draws_never_justify_a_call_on_the_river():
    assert not should_call_with_draw(["Ad", "Kd"], ["9d", "6d", "2h", "3s", "7c"], "river", to_call=1.0, pot_before=100.0)


def test_no_draw_no_call():
    assert not should_call_with_draw(["Ks", "Qh"], ["9d", "6h", "2s"], "flop", to_call=1.0, pot_before=100.0)


def _hero_facing_a_flop_bet_from_bb():
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG (seat 4) opens, has initiative
    for s in (5, 6, 1, 2):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    hand.apply_action(3, "call")  # BB calls
    assert hand.street == "flop"
    hand.board = ["9c", "6d", "2h"]
    hand.apply_action(3, "bet", amount=3.0)  # BB (seat 3) leads into hero
    return hand


def test_folds_bottom_pair_to_a_bet_with_no_opponent_info(monkeypatch):
    # Hero (UTG) is in position vs the BB bettor here, so FLOAT_FLOP_IN_
    # POSITION (True by default since 2026-08-17) would otherwise call this
    # spot as a float -- isolate it off since this test's actual target is
    # the plain "no hand, no draw, no float rule" fold path.
    monkeypatch.setattr(abc_bot, "FLOAT_FLOP_IN_POSITION", False)
    hand = _hero_facing_a_flop_bet_from_bb()
    hand.players[4].hole_cards = ["6s", "3d"]  # bottom pair (6s) -- not top-pair-or-better
    action, _ = choose_abc_action(hand, 4)
    assert action == "fold"


def test_folds_bottom_pair_to_a_known_nit_bettor(monkeypatch):
    monkeypatch.setattr(abc_bot, "FLOAT_FLOP_IN_POSITION", False)
    hand = _hero_facing_a_flop_bet_from_bb()
    hand.players[4].hole_cards = ["6s", "3d"]
    action, _ = choose_abc_action(hand, 4, opponent_archetypes={3: "Nit"})
    assert action == "fold"


def test_calls_bottom_pair_against_a_known_loose_archetype_bettor():
    hand = _hero_facing_a_flop_bet_from_bb()
    hand.players[4].hole_cards = ["6s", "3d"]
    action, _ = choose_abc_action(hand, 4, opponent_archetypes={3: "Station"})
    assert action == "call"


def _three_way_flop():
    # UTG (4) opens, MP (5) calls, BB (3) calls -- a genuine 3-way pot (4, 5, 3 live).
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)
    hand.apply_action(5, "call")
    for s in (6, 1, 2):
        hand.apply_action(s, "fold")
    hand.apply_action(3, "call")
    assert hand.street == "flop"
    hand.board = ["9c", "6d", "2h"]
    return hand


def test_does_not_cbet_with_air_in_a_multiway_pot(monkeypatch):
    # These sub-rules ship OFF by default (empirically the original bundle
    # cost real bb/100 against this population's real bot mix -- see the
    # v11/v18 module docstring notes), but the feature itself is still
    # correct and tested here.
    monkeypatch.setattr(abc_bot, "MULTIWAY_DISABLE_AIR_CBET", True)
    hand = _three_way_flop()
    hand.apply_action(hand.current_actor(), "check")  # BB checks
    actor = hand.current_actor()
    assert actor == 4  # hero, had initiative
    hand.players[4].hole_cards = ["Ac", "Qd"]  # total air on this board
    action, _ = choose_abc_action(hand, 4)
    assert action == "check"  # no free-roll cbet with 2+ opponents live


def test_does_not_loosen_vs_loose_archetype_in_a_multiway_pot(monkeypatch):
    # needs both: the cbet-suppression is scaffolding to reach a check-around
    # flop below, the loose-call suppression is the actual thing under test.
    monkeypatch.setattr(abc_bot, "MULTIWAY_DISABLE_AIR_CBET", True)
    monkeypatch.setattr(abc_bot, "MULTIWAY_DISABLE_LOOSE_CALL", True)
    hand = _three_way_flop()
    hand.apply_action(hand.current_actor(), "check")  # BB (3) checks
    hand.players[4].hole_cards = ["Ac", "Qd"]
    action, _ = choose_abc_action(hand, 4)
    assert action == "check"  # hero also checks (air, multiway suppresses the cbet)
    hand.apply_action(4, "check")
    aggressor = hand.current_actor()
    assert aggressor == 5
    hand.apply_action(5, "bet", amount=6.0)  # MP (5), a known loose archetype, bets
    assert hand.current_actor() == 3
    hand.apply_action(3, "call")  # BB stays live too -- still a genuine 3-way pot
    assert hand.current_actor() == 4
    hand.players[4].hole_cards = ["6s", "3d"]  # bottom pair
    action, _ = choose_abc_action(hand, 4, opponent_archetypes={5: "Station"})
    assert action == "fold"  # would call heads-up, but multiway suppresses the loosened bar


def test_does_not_cold_call_a_raise_already_called_by_someone_else(monkeypatch):
    monkeypatch.setattr(abc_bot, "MULTIWAY_NARROW_CALL_RANGE", True)
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG opens
    hand.apply_action(5, "call")  # MP already calls -- forming multiway pot
    for s in (6, 1, 2):
        hand.apply_action(s, "fold")
    bb_seat = hand.current_actor()
    assert bb_seat == 3
    hand.players[bb_seat].hole_cards = ["Jd", "Td"]  # JTs -- in the call range, not premium
    action, _ = choose_abc_action(hand, bb_seat)
    assert action == "fold"  # would call heads-up (see the non-multiway test above), but not here


def test_very_strong_hand_detection():
    # two pair -- strictly stronger than has_top_pair_or_better's bar
    assert has_very_strong_hand(["9h", "6d"], ["9c", "6h", "2s"])
    assert has_very_strong_hand(["9h", "9d"], ["9c", "6h", "2s"])  # trips
    assert has_very_strong_hand(["Jd", "Td"], ["9d", "8d", "2d"])  # made flush
    assert has_very_strong_hand(["9c", "8c"], ["7d", "6h", "5s", "2c"])  # made straight
    # plain top pair / overpair are NOT very strong -- call-only, not raise
    assert not has_very_strong_hand(["Ah", "Kd"], ["Ac", "7d", "2s"])  # top pair aces
    assert not has_very_strong_hand(["9h", "9d"], ["8c", "7d", "2s"])  # overpair, not two pair+


def test_trips_or_better_detection_excludes_plain_two_pair():
    assert has_trips_or_better(["9h", "9d"], ["9c", "6h", "2s"])  # trips
    assert has_trips_or_better(["Kh", "Kd"], ["Kc", "6h", "6s"])  # full house (trip kings + board pair)
    assert has_trips_or_better(["Jd", "Td"], ["9d", "8d", "2d"])  # made flush
    assert has_trips_or_better(["9c", "8c"], ["7d", "6h", "5s", "2c"])  # made straight
    # plain two pair is excluded from this narrower tier (unlike has_very_strong_hand)
    assert not has_trips_or_better(["9h", "6d"], ["9c", "6h", "2s"])
    assert not has_trips_or_better(["Ah", "Kd"], ["Ac", "7d", "2s"])  # top pair, not this tier at all
    assert not has_very_strong_hand(["Kc", "Qh"], ["9d", "6h", "2s"])  # no made hand at all


def test_calls_two_pair_facing_a_bet_by_default_value_raise_shipped_off():
    # v22 tested VALUE_RAISE_FACING_BET and measured it WORSE (-9.66 bb/100,
    # see abc_bot.py's changelog) -- shipped False, so even a genuine monster
    # like two pair still just calls in the live default, same as before v22.
    hand = _hero_facing_a_flop_bet_from_bb()
    hand.players[4].hole_cards = ["9s", "6s"]  # two pair (9s+6s vs board 9c/6d) on a 9c-6d-2h board
    action, _ = choose_abc_action(hand, 4)
    assert action == "call"


def test_value_raises_two_pair_facing_a_bet_when_flag_is_flipped_on(monkeypatch):
    # The mechanism itself, gated behind the flag for anyone re-testing this
    # later -- see the module docstring for why it's off by default.
    monkeypatch.setattr(abc_bot, "VALUE_RAISE_FACING_BET", True)
    monkeypatch.setattr(abc_bot, "HERO_PROGRESSIVE_POT_DAMPING", False)  # isolate the raise sizing from pot damping
    hand = _hero_facing_a_flop_bet_from_bb()
    hand.players[4].hole_cards = ["9s", "6s"]
    action, amount = choose_abc_action(hand, 4)
    assert action == "raise"
    assert amount == 9.0  # 3x the 3bb bet faced (VALUE_RAISE_MULTIPLIER), damping isolated off


def test_value_raise_sizing_is_damped_in_an_already_big_pot_when_flag_is_flipped_on(monkeypatch):
    # Same very-strong hand and bet, both gated flags flipped on. Damping now
    # defaults off after the 2026-08-12 ablation result, but the mechanism
    # stays testable for anyone who wants to re-check it later.
    monkeypatch.setattr(abc_bot, "VALUE_RAISE_FACING_BET", True)
    monkeypatch.setattr(abc_bot, "HERO_PROGRESSIVE_POT_DAMPING", True)
    hand = _hero_facing_a_flop_bet_from_bb()
    hand.players[4].hole_cards = ["9s", "6s"]
    action, amount = choose_abc_action(hand, 4)
    assert action == "raise"
    assert 3.0 < amount < 9.0  # damped below the undamped 3x-the-bet sizing, still a real raise


def test_calls_plain_top_pair_facing_a_bet_instead_of_raising():
    hand = _hero_facing_a_flop_bet_from_bb()
    hand.players[4].hole_cards = ["9h", "Kd"]  # top pair nines, no second pair -- call, not raise
    action, _ = choose_abc_action(hand, 4)
    assert action == "call"


def test_never_value_raises_as_a_bluff_with_a_weak_hand_even_with_flag_on(monkeypatch):
    monkeypatch.setattr(abc_bot, "VALUE_RAISE_FACING_BET", True)
    # Isolate FLOAT_FLOP_IN_POSITION (True by default since 2026-08-17) --
    # this test's target is confirming VALUE_RAISE_FACING_BET doesn't
    # mistakenly fire as a bluff-raise, not the separate float-call line.
    monkeypatch.setattr(abc_bot, "FLOAT_FLOP_IN_POSITION", False)
    hand = _hero_facing_a_flop_bet_from_bb()
    hand.players[4].hole_cards = ["6s", "3d"]  # bottom pair -- not very strong, rule doesn't apply even with the flag on
    action, _ = choose_abc_action(hand, 4)
    assert action == "fold"


def test_is_wet_board_detection():
    assert _is_wet_board(["9d", "8d", "2d"])  # monotone -- made flush possible
    assert _is_wet_board(["9d", "8h", "2d"])  # two-tone -- flush draw possible
    assert _is_wet_board(["9c", "8h", "7s"])  # highly connected -- straight-drawy
    assert not _is_wet_board(["Kd", "7c", "2s"])  # dry rainbow, disconnected
    assert not _is_wet_board(["Kd", "7c"])  # incomplete board -- never "wet" (not enough cards yet)


def test_sizes_up_with_very_strong_hand_when_flag_is_on(monkeypatch):
    monkeypatch.setattr(abc_bot, "SIZE_UP_WITH_VERY_STRONG_HAND", True)
    hand, bb_seat = _bb_free_flop()
    hand.board = ["9c", "9d", "2h"]
    hand.players[bb_seat].hole_cards = ["9s", "2d"]  # trips + a board pair -- two-pair-or-better, very_strong
    _, amount_sized_up = choose_abc_action(hand, bb_seat)

    monkeypatch.setattr(abc_bot, "SIZE_UP_WITH_VERY_STRONG_HAND", False)
    hand2, bb_seat2 = _bb_free_flop()
    hand2.board = ["9c", "9d", "2h"]
    hand2.players[bb_seat2].hole_cards = ["9s", "2d"]
    _, amount_baseline = choose_abc_action(hand2, bb_seat2)

    assert amount_sized_up > amount_baseline


def test_sizes_up_on_wet_board_when_flag_is_on(monkeypatch):
    monkeypatch.setattr(abc_bot, "SIZE_UP_ON_WET_BOARD", True)
    hand, bb_seat = _bb_free_flop()
    hand.board = ["9d", "8d", "2d"]  # monotone -- wet
    hand.players[bb_seat].hole_cards = ["9s", "Kd"]  # top pair, plain -- made but not very_strong
    _, amount_sized_up = choose_abc_action(hand, bb_seat)

    monkeypatch.setattr(abc_bot, "SIZE_UP_ON_WET_BOARD", False)
    hand2, bb_seat2 = _bb_free_flop()
    hand2.board = ["9d", "8d", "2d"]
    hand2.players[bb_seat2].hole_cards = ["9s", "Kd"]
    _, amount_baseline = choose_abc_action(hand2, bb_seat2)

    assert amount_sized_up > amount_baseline


def _heads_up_flop_cbet_spot():
    # UTG opens, BB calls, flop checked to UTG (who has initiative) -- the
    # unconditional-flop-cbet-with-air spot, same shape as
    # _reach_turn_with_initiative's setup but stopping BEFORE the cbet so
    # the amount can be inspected directly.
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG (seat 4) opens, will have initiative
    for s in (5, 6, 1, 2):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    hand.apply_action(3, "call")  # BB calls
    assert hand.street == "flop"
    hand.board = ["9c", "6d", "2h"]
    hand.apply_action(3, "check")
    assert hand.current_actor() == 4
    return hand


def test_does_not_size_up_a_bluff_cbet_with_the_strength_flag(monkeypatch):
    # should_bet can also fire from cbet_with_air (no made hand at all) --
    # SIZE_UP_WITH_VERY_STRONG_HAND must stay a no-op there (`made and
    # very_strong` correctly requires a REAL made hand, which air never has).
    monkeypatch.setattr(abc_bot, "SIZE_UP_WITH_VERY_STRONG_HAND", True)
    hand = _heads_up_flop_cbet_spot()
    hand.players[4].hole_cards = ["Ac", "Qd"]  # total air on this board
    action, amount_flagged = choose_abc_action(hand, 4)
    assert action == "bet"  # unconditional flop cbet with initiative, heads-up

    monkeypatch.setattr(abc_bot, "SIZE_UP_WITH_VERY_STRONG_HAND", False)
    hand2 = _heads_up_flop_cbet_spot()
    hand2.players[4].hole_cards = ["Ac", "Qd"]
    _, amount_baseline = choose_abc_action(hand2, 4)

    assert amount_flagged == amount_baseline  # air never triggers the size-up, flag or not


def _hero_facing_an_overbet_from_bb(bet_multiple_of_pot: float):
    players = make_players(6)
    hand = Hand(players, button_seat=1, small_blind=1.0, big_blind=2.0)
    hand.apply_action(4, "raise", amount=5.0)  # UTG (seat 4) opens, has initiative
    for s in (5, 6, 1, 2):
        if hand.current_actor() == s:
            hand.apply_action(s, "fold")
    hand.apply_action(3, "call")  # BB calls
    assert hand.street == "flop"
    hand.board = ["9c", "6d", "2h"]
    pot_before_the_bet = sum(p.total_contributed for p in hand.players.values())
    hand.apply_action(3, "check")  # BB checks to hero (seat 4), who bets into hero
    hand.apply_action(4, "bet", amount=pot_before_the_bet * bet_multiple_of_pot)
    return hand


def test_folds_plain_top_pair_to_a_genuine_overbet_when_flag_on(monkeypatch):
    # 2026-08-12 bug fix regression test: the original formula compared
    # to_call against a `pot_before` that already included the opponent's
    # bet, making a "bet > pot" overbet mathematically unreachable (a
    # 300,000-hand probe confirmed exactly zero divergent hands before this
    # fix). This uses a real 1.5x-pot bet -- a genuine overbet -- and
    # asserts the fold actually fires now.
    monkeypatch.setattr(abc_bot, "FOLD_TOP_PAIR_VS_OVERBET", True)
    hand = _hero_facing_an_overbet_from_bb(1.5)
    hero = hand.current_actor()
    hand.players[hero].hole_cards = ["9s", "Kd"]  # plain top pair (nines), not very_strong
    action, _ = choose_abc_action(hand, hero)
    assert action == "fold"


def test_still_calls_plain_top_pair_facing_an_overbet_when_flag_off():
    hand = _hero_facing_an_overbet_from_bb(1.5)
    hero = hand.current_actor()
    hand.players[hero].hole_cards = ["9s", "Kd"]
    action, _ = choose_abc_action(hand, hero)
    assert action == "call"


def test_still_calls_plain_top_pair_facing_a_sub_pot_bet_when_flag_on(monkeypatch):
    # 0.75x pot is a big bet but NOT an overbet -- the fold should not fire.
    monkeypatch.setattr(abc_bot, "FOLD_TOP_PAIR_VS_OVERBET", True)
    hand = _hero_facing_an_overbet_from_bb(0.75)
    hero = hand.current_actor()
    hand.players[hero].hole_cards = ["9s", "Kd"]
    action, _ = choose_abc_action(hand, hero)
    assert action == "call"


def test_very_strong_hand_still_calls_a_genuine_overbet_when_flag_on(monkeypatch):
    monkeypatch.setattr(abc_bot, "FOLD_TOP_PAIR_VS_OVERBET", True)
    hand = _hero_facing_an_overbet_from_bb(1.5)
    hero = hand.current_actor()
    hand.players[hero].hole_cards = ["9s", "9d"]  # trips nines -- very_strong, never folds here
    action, _ = choose_abc_action(hand, hero)
    assert action == "call"
