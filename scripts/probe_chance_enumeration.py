#!/usr/bin/env python3
"""Chance-node enumeration after the first baseline/treatment split.

Default methodology for this script:
- run baseline and treatment in lockstep on the same hand;
- when hero's action first differs, average the continuation over every
  possible next board card;
- count that whole averaged branch as ONE observation, not as 30-45 hands.

Known caveats / failure modes:
- This script is still a per-hand EV probe, not the full session simulator:
  each hand starts from fresh 200bb stacks, so it intentionally removes
  cross-hand bankroll/turnover feedback.
- It enumerates only the NEXT board card, not the full turn+river tree. If
  most noise is from later betting decisions or the full runout, CI can remain
  wide.
- It only enumerates after the first HERO action split. Non-hero stochastic
  divergence is controlled with common-random seeds, not fully branched.
- Branches must never be counted as independent samples. One divergent hand
  contributes one averaged delta; otherwise CI is falsely overconfident.
- Very rare flags still need enough independent divergent hands. Enumerating
  40 cards for two spots does not prove the population effect.
- This is CPU-expensive when splits are frequent. Always compare CI shrink
  against slowdown before using it for a large batch.
"""

import copy
import math
import random
import statistics
import sys
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(__file__).rsplit("/scripts/", 1)[0])

import backend.bots.abc_bot as abc_bot
from backend.bots.abc_bot import choose_abc_action
from backend.bots.behavior_clone import choose_bot_action
from backend.engine.cards_import import Card
from backend.engine.hand import IllegalAction
from backend.engine.table import Table
from backend.sessions.live_dynamics import ARCHETYPE_POOL, TableTurnover
from scripts.simulate_abc_bot import (
    BOT_ACTION_SEED_STREAM,
    DECK_SEED_STREAM,
    HERO_HAND_SEED_STREAM,
    HERO_SEAT,
    MAX_SEATS,
    OPPONENT_HAND_SEED_STREAM,
    PRESET_FLAG_GROUPS,
    RAKE_CAP_BB,
    RAKE_PERCENT,
    STARTING_STACK,
    TILT_SEED_STREAM,
    _NON_BOOLEAN_FLAG_OFF_VALUES,
    _NON_BOOLEAN_FLAG_ON_VALUES,
    _common_seed,
    _sync_value_3bet,
)

# 2026-08-21: real population incidence, restricted to players who tilt at
# all (same conditioning as PokerDom_Microlimits_Analysis/scripts/
# check_tilt_after_cooler.py's feat_rel) -- 768,494 post-cooler (hand,
# player) pairs out of 19,211,339 total for that subpopulation. Sampled
# per hand per opponent (NOT accumulated via TableTurnover's live
# tracking, which this probe's fresh-stacks-every-hand design can't yet
# feed a real cooler sequence into) -- see WIDER_CALL_VS_TILTING_OPPONENT's
# comment in abc_bot.py for why this ground-truth-ceiling approach is a
# disclosed simplification, not the full live picture.
TILT_TIER_WEIGHTS = {"none": 18_442_845, "acute": 191_623, "fading": 244_897, "residual": 331_974}

EXTRA_TEST_GROUPS = {
    "v3-calling-raises": (["ALLOW_CALLING_RAISES"], "v3 allow calling raises"),
    "v6-unconditional-cbet": (["UNCONDITIONAL_FLOP_CBET"], "v6 unconditional flop cbet"),
    "v10-opponent-aware": (["OPPONENT_AWARE_ARCHETYPES"], "v10 opponent-aware loose calls"),
    "v11-multiway-aware": (
        ["MULTIWAY_NARROW_CALL_RANGE", "MULTIWAY_DISABLE_AIR_CBET", "MULTIWAY_DISABLE_LOOSE_CALL"],
        "v11 multiway aware",
    ),
    # 2026-08-17: v18 (2026-08-07) already tested these three individually,
    # but with the old whole-game simulation method (noisier CIs than
    # chance-enumeration). Two of the three had clean separation from zero
    # (disable-air-cbet -7.94, disable-loose-call -5.91) -- re-testing
    # mainly to cross-check with the modern, lower-variance method, same
    # precedent as SIZE_UP_PREMIUM_OPENS getting reversed on re-check.
    # narrow-call-range was explicitly borderline in the old test (-3.96
    # with rake, +1.04 without -- inside/at the edge of CI), the most
    # likely of the three to actually change verdict here.
    "multiway-disable-air-cbet": (
        ["MULTIWAY_DISABLE_AIR_CBET"],
        "flop air cbet only fires heads-up, made-hand-only in multiway (v18 sub-rule 2, re-check with chance-enumeration)",
    ),
    "multiway-disable-loose-call": (
        ["MULTIWAY_DISABLE_LOOSE_CALL"],
        "any-pair-or-better call vs a known loose archetype only applies heads-up (v18 sub-rule 3, re-check with chance-enumeration)",
    ),
    "multiway-narrow-call-range": (
        ["MULTIWAY_NARROW_CALL_RANGE"],
        "facing a raise already called by someone, only continue with VALUE_3BET-tier hands in multiway (v18 sub-rule 1, re-check with chance-enumeration -- was borderline in the old test)",
    ),
    "v14-steal-wide": (["STEAL_WIDER_VS_NIT"], "v14 steal wider vs nit"),
    "v14-size-target": (["SIZING_TARGET_ARCHETYPES"], "v14 value size target archetypes"),
    "v15-loose-3bet": (["WIDER_3BET_VS_LOOSE"], "v15 wider 3bet vs loose"),
    "v15-turn-size": (["SIZE_UP_ON_TURN"], "v15 size up on turn"),
    "v19-hero-pot-damping": (["HERO_PROGRESSIVE_POT_DAMPING"], "v19 hero pot damping"),
    "v21-squeeze-wide": (["SQUEEZE_WIDER_RANGE"], "v21 squeeze wider range"),
    "v21-squeeze-size": (["SQUEEZE_SIZE_UP_PER_CALLER"], "v21 squeeze size up per caller"),
    "v21-squeeze-both": (["SQUEEZE_WIDER_RANGE", "SQUEEZE_SIZE_UP_PER_CALLER"], "v21 squeeze wider+size"),
    "v22-value-raise": (["VALUE_RAISE_FACING_BET"], "v22 value raise two-pair+"),
    "v22-value-raise-trips": (
        ["VALUE_RAISE_FACING_BET", "VALUE_RAISE_TRIPS_OR_BETTER_ONLY"],
        "v22 value raise trips+ only",
    ),
    "v23-overbet-fold": (["FOLD_TOP_PAIR_VS_OVERBET"], "v23 fold top pair vs overbet"),
    "v23-size-strong": (["SIZE_UP_WITH_VERY_STRONG_HAND"], "v23 size up strong hand"),
    "v23-size-wet": (["SIZE_UP_ON_WET_BOARD"], "v23 size up wet board"),
    "v23-size-both": (["SIZE_UP_WITH_VERY_STRONG_HAND", "SIZE_UP_ON_WET_BOARD"], "v23 size up strong+wet"),
    "v24-bluff-3bet": (["BLUFF_3BET_VS_TIGHT"], "v24 bluff 3bet vs tight"),
}

RULE_TEST_GROUPS = {
    "r01-calling-raises": (["ALLOW_CALLING_RAISES"], "r01 calling raises"),
    "r02-unconditional-cbet": (["UNCONDITIONAL_FLOP_CBET"], "r02 unconditional flop cbet"),
    "r03-opponent-aware-loose-call": (["OPPONENT_AWARE_ARCHETYPES"], "r03 opponent-aware loose calls"),
    "r04-wide-value-3bet": (["USE_WIDE_VALUE_3BET"], "r04 wide value 3bet"),
    "r05-steal-wide-vs-nit": (["STEAL_WIDER_VS_NIT"], "r05 steal wider vs nit"),
    "r06-size-up-vs-nit-tag": (["SIZING_TARGET_ARCHETYPES"], "r06 value size target archetypes"),
    "r07-wider-3bet-vs-loose": (["WIDER_3BET_VS_LOOSE"], "r07 wider 3bet vs loose"),
    "r08-size-up-turn": (["SIZE_UP_ON_TURN"], "r08 size up on turn"),
    "r09-iso-raise-limpers": (["ISO_RAISE_OVER_LIMPERS"], "r09 iso-raise over limpers"),
    "r10-donk-bluff-vs-tight": (["DONK_BLUFF_VS_TIGHT"], "r10 donk bluff vs tight"),
    "r11-hero-pot-damping": (["HERO_PROGRESSIVE_POT_DAMPING"], "r11 hero progressive pot damping"),
    "r12-tight-big-iso-limpers": (["TIGHT_BIG_ISO_RAISE_LIMPERS"], "r12 tight big iso-raise limpers"),
    "r13-shove-aa-kk-vs-3bet-plus": (["SHOVE_AA_KK_VS_3BET_PLUS"], "r13 shove AA/KK vs 3bet+"),
    "r14-bluff-3bet-vs-tight": (["BLUFF_3BET_VS_TIGHT"], "r14 bluff 3bet vs tight"),
    "r20-size-up-premium-opens": (["SIZE_UP_PREMIUM_OPENS"], "r20 size up premium opens (re-test of v19b w/ chance-enum)"),
    "r21-tight-iso-real-data-floor": (
        ["TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR"],
        "r21 tight-iso range unions REAL_DATA_RANGE_ADDITIONS (currently omitted, unlike open/steal ranges)",
    ),
    "r22-threebet-size-by-position": (
        ["THREEBET_SIZE_BY_POSITION"],
        "r22 3-bet sizing bigger OOP / smaller IP instead of a flat 3x multiplier",
    ),
    "r23-threebet-bluff-late-position": (
        ["THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT"],
        "r23 bluff-3bet from late position regardless of raiser archetype (polarization)",
    ),
    "r24-bb-defend-mdf-scaled": (
        ["BB_DEFEND_MDF_SCALED"],
        "r24 BB continuing range scaled by minimum defense frequency (MDF), any raiser position",
    ),
    "r25-bluff-3bet-blocker-range": (
        ["BLUFF_3BET_BLOCKER_RANGE_FLAG"],
        "r25 bluff-3bet hand selection built from blocker theory (wheel aces) instead of playability",
    ),
    "r26-limp-trap-monsters": (
        ["LIMP_TRAP_WITH_MONSTERS"],
        "r26 limp-reraise trap with AA/KK from an unopened pot",
    ),
    "r27-set-mine-implied-odds": (
        ["SET_MINE_IMPLIED_ODDS"],
        "r27 explicit 15/25/35-rule implied-odds cold-call for pocket pairs / suited connectors",
    ),
    "r28-rake-adjusted-open-sizing": (
        ["RAKE_ADJUSTED_OPEN_SIZING"],
        "r28 smaller UTG/MP open size (2.2bb) reflecting rake-adjustment theory",
    ),
    "r29-fold-vs-3bet-passive": (
        ["FOLD_VS_3BET_FROM_PASSIVE"],
        "r29 fold QQ/AKs/AKo facing a 3bet+ specifically from a known loose-passive raiser",
    ),
    # pf1-pf10 (2026-08-14 postflop research batch, see CLAUDE.md and abc_bot.py's
    # docstring): built + smoke-tested for crashes only, none statistically tested.
    "pf1-texture-dependent-cbet-sizing": (
        ["TEXTURE_DEPENDENT_CBET_SIZING"],
        "pf1 smaller flop air c-bet on a dry board",
    ),
    "pf3-semi-bluff-raise-draws": (
        ["SEMI_BLUFF_RAISE_DRAWS"],
        "pf3 raise (not just call) a strong flop draw, heads-up",
    ),
    "semi-bluff-raise-draws-turn": (
        ["SEMI_BLUFF_RAISE_DRAWS_TURN"],
        "extend pf3's semi-bluff raise to the turn (flop already confirmed True, turn was flagged untested)",
    ),
    "smaller-bluff-on-wet-board": (
        ["SMALLER_BLUFF_ON_WET_BOARD"],
        "smaller size (33% pot) for a plain air bluff (cbet/donk-bluff/barrel-bluff) on a wet board instead of standard sizing",
    ),
    "pf4-nut-advantage-sizing": (
        ["NUT_ADVANTAGE_SIZING"],
        "pf4 size up a value bet when the board favors hero's own preflop-raiser range",
    ),
    "pf5-probe-bet-turn-after-check": (
        ["PROBE_BET_TURN_AFTER_CHECK"],
        "pf5 probe-bet the turn after a checked-through flop, without initiative",
    ),
    "pf6-pot-control-marginal-hands": (
        ["POT_CONTROL_MARGINAL_HANDS"],
        "pf6 check back a marginal made hand OOP, multiway, wet board",
    ),
    "pf7-spr-scaled-thresholds": (
        ["SPR_SCALED_THRESHOLDS"],
        "pf7 widen the calling bar to any-pair-or-better when SPR is already low",
    ),
    "pf8-block-bet-river": (
        ["BLOCK_BET_RIVER"],
        "pf8 small ~30% pot river block-bet tier for thin value OOP",
    ),
    "pf9-blocker-based-river-bluff": (
        ["BLOCKER_BASED_RIVER_BLUFF"],
        "pf9 require a blocker card before firing the existing BARREL_BLUFF_VS_TIGHT",
    ),
    "pf10-delayed-cbet-marginal": (
        ["DELAYED_CBET_MARGINAL"],
        "pf10 delay the flop air c-bet some of the time, bet turn instead if checked to again",
    ),
    "v27-river-overbet-nuts-vs-loose": (
        ["RIVER_OVERBET_NUTS_VS_LOOSE"],
        "v27 genuine river overbet (150% pot) with trips-or-better vs a known loose/weak archetype",
    ),
    "turn-overbet-nuts-vs-loose": (
        ["TURN_OVERBET_NUTS_VS_LOOSE"],
        "turn analogue of v27: genuine overbet (150% pot) with trips-or-better vs a known loose/weak archetype, generalized off river-only",
    ),
    # 2026-08-17 (user-prompted "check sizings, SB strategy, postflop gaps"
    # research pass): new flags, none tested yet.
    "sized-4bet-instead-of-shove": (
        ["SIZED_4BET_INSTEAD_OF_SHOVE"],
        "sized (~2.3-2.6x) 4-bet instead of an all-in shove with the SHOVE_AA_KK_VS_3BET_PLUS range",
    ),
    "sb-bigger-open-sizing": (
        ["SB_BIGGER_OPEN_SIZING"],
        "open to 3bb instead of 2.5bb from SB specifically in the blind-vs-blind (no limpers) case",
    ),
    "sb-threebet-or-fold-vs-steal": (
        ["SB_THREEBET_OR_FOLD_VS_STEAL"],
        "SB 3-bets its whole continue range facing a CO/BTN/SB steal instead of ever flat-calling",
    ),
    "fold-marginal-vs-check-raise": (
        ["FOLD_MARGINAL_VS_CHECK_RAISE"],
        "fold a plain top-pair-tier hand (not very_strong) facing a genuine check-raise, heads-up, non-loose aggressor",
    ),
    "float-flop-in-position": (
        ["FLOAT_FLOP_IN_POSITION"],
        "call a flop bet in position with no hand/draw, bet the turn if checked to again",
    ),
    "float-turn-in-position": (
        ["FLOAT_TURN_IN_POSITION"],
        "call a turn bet in position with no hand/draw, bet the river if checked to again -- FLOAT_FLOP_IN_POSITION generalized one street later",
    ),
    "size-up-premium-3bets": (
        ["SIZE_UP_PREMIUM_3BETS"],
        "size up the value 3-bet with a premium hand -- SIZE_UP_PREMIUM_OPENS generalized to the 3-bet",
    ),
    "wider-call-vs-tilting-opponent": (
        ["WIDER_CALL_VS_TILTING_OPPONENT"],
        "call with any pair or better vs an aggressor currently in a real, live-accumulated post-cooler tilt window (record_hand_for_tilt across this probe run's own hand sequence)",
    ),
    "bluff-catch-vs-frequent-bluffer-a": (
        ["BLUFF_CATCH_VS_FREQUENT_BLUFFER_A"],
        "call with any pair or better vs an aggressor read as bluff_tier_a=high (last river aggressor, reached real showdown, lost -- reliable at >=15 river showdowns, 777/26797 players)",
    ),
    "bluff-catch-vs-frequent-bluffer-c": (
        ["BLUFF_CATCH_VS_FREQUENT_BLUFFER_C"],
        "call with any pair or better vs an aggressor read as bluff_tier_c=high (any-street aggressor, reached real showdown, lost -- reliable at >=15 events, 7974/26797 players)",
    ),
    # 2026-08-17, later same day: closing the last 3 postflop gaps from the
    # overnight audit.
    "fold-marginal-vs-big-donk": (
        ["FOLD_MARGINAL_VS_BIG_DONK"],
        "fold a plain top-pair-tier hand to a BIG (>=66% pot) donk lead specifically while hero has preflop initiative",
    ),
    "fold-top-pair-vs-wet-board-tight": (
        ["FOLD_TOP_PAIR_VS_WET_BOARD_TIGHT"],
        "fold a plain top-pair-tier hand to a real-sized bet on a wet board from a known tight archetype",
    ),
    "river-bluff-missed-draw": (
        ["RIVER_BLUFF_MISSED_DRAW"],
        "bluff the river when checked to after a real flush/straight draw missed, vs a known tight archetype",
    ),
    "wider-call-vs-often-tier": (
        ["WIDER_CALL_VS_OFTEN_TIER"],
        "call with any pair or better vs an aggressor read as postflop_freq_tier=often, generalizing LOOSE_ARCHETYPES across the orthogonal axis",
    ),
    # 2026-08-17, follow-up round: diagnostic-only (never meant to ship) --
    # see SB_FOLD_VS_STEAL_DIAGNOSTIC's comment in abc_bot.py. Answers
    # "is SB's flat-call range vs a steal positive EV at all" (vs a pure
    # fold), not "is 3-betting better than calling" (already answered by
    # sb-threebet-or-fold-vs-steal above). flag_names here is unused by
    # _build_comparison's special-cased branch for this preset -- listed
    # only so the top-level preset lookup succeeds.
    "sb-flat-call-vs-fold-diagnostic": (
        ["SB_THREEBET_OR_FOLD_VS_STEAL", "SB_FOLD_VS_STEAL_DIAGNOSTIC"],
        "diagnostic: SB's flat-call range vs a steal, compared to folding the same range (both arms force SB_THREEBET_OR_FOLD_VS_STEAL off)",
    ),
    "tight-iso-tightens-per-limper": (
        ["TIGHT_ISO_TIGHTENS_PER_EXTRA_LIMPER"],
        "narrow the tight-big-iso range further for each limper beyond the first (0.85x compounding per extra limper), instead of only scaling sizing",
    ),
}

TIGHT_ISO_PARAM_FLAGS = [
    "TIGHT_BIG_ISO_RAISE_LIMPERS",
    "TIGHT_ISO_VPIP_MULTIPLIER",
    "TIGHT_ISO_BASE_SIZING_BB",
    "TIGHT_ISO_SIZING_PER_LIMPER_BB",
]

TIGHT_ISO_VARIANTS = {
    "r12v-tight-same-size": (0.55, 4.5, 1.0),
    "r12v-wide-same-size": (0.85, 4.5, 1.0),
    "r12v-current-smaller": (0.70, 3.5, 0.5),
    "r12v-current-bigger": (0.70, 5.5, 1.5),
    "r12v-tight-bigger": (0.55, 5.5, 1.5),
    "r12v-wide-smaller": (0.85, 3.5, 0.5),
    # 2026-08-17: published-theory sizing (Upswing/PreflopWizard/2+2 consensus:
    # base open size + 1bb/limper, i.e. ~4bb + 1bb/limper live, 3bb + 1bb/limper
    # online) -- notably smaller than the currently-shipped 5.5bb+1.5bb/limper.
    # Keeps the already-confirmed-best 0.85 VPIP width, isolates the sizing
    # question specifically. User asked to verify whether the shipped sizing
    # (well above any published number) is actually correct for this population
    # or just an artifact of testing a narrow candidate set that never included
    # anything this small.
    "r12v-published-theory": (0.85, 4.0, 1.0),
}

TIGHT_ISO_VARIANT_GROUPS = {
    name: (
        TIGHT_ISO_PARAM_FLAGS,
        f"{name} vs current tight iso ({mult:.2f}x open, {base:.1f}bb + {per:.1f}bb/limper)",
    )
    for name, (mult, base, per) in TIGHT_ISO_VARIANTS.items()
}

PARAMETER_VARIANTS: dict[str, tuple[list[str], dict[str, object], str]] = {
    "r14v-bluff-3bet-nit-only": (
        ["BLUFF_3BET_VS_TIGHT", "BLUFF_3BET_TARGET_ARCHETYPES"],
        {"BLUFF_3BET_VS_TIGHT": True, "BLUFF_3BET_TARGET_ARCHETYPES": {"Nit"}},
        "r14v bluff 3bet vs Nit only",
    ),
    "r14v-bluff-3bet-tag-only": (
        ["BLUFF_3BET_VS_TIGHT", "BLUFF_3BET_TARGET_ARCHETYPES"],
        {"BLUFF_3BET_VS_TIGHT": True, "BLUFF_3BET_TARGET_ARCHETYPES": {"TAG"}},
        "r14v bluff 3bet vs TAG only",
    ),
    "r14v-bluff-3bet-nit-tag": (
        ["BLUFF_3BET_VS_TIGHT", "BLUFF_3BET_TARGET_ARCHETYPES"],
        {"BLUFF_3BET_VS_TIGHT": True, "BLUFF_3BET_TARGET_ARCHETYPES": {"Nit", "TAG"}},
        "r14v bluff 3bet vs Nit+TAG",
    ),
    "r14v-bluff-3bet-lag-only": (
        ["BLUFF_3BET_VS_TIGHT", "BLUFF_3BET_TARGET_ARCHETYPES"],
        {"BLUFF_3BET_VS_TIGHT": True, "BLUFF_3BET_TARGET_ARCHETYPES": {"LAG"}},
        "r14v bluff 3bet vs LAG only",
    ),
    "r15v-fold-qq-vs-nit-tag-50": (
        [
            "FOLD_PREMIUM_VS_EXTREME_AGGRO",
            "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO",
            "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD",
            "EXTREME_AGGRO_STACK_FRACTION",
        ],
        {
            "FOLD_PREMIUM_VS_EXTREME_AGGRO": True,
            "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO": {"QQ"},
            "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD": {"Nit", "TAG"},
            "EXTREME_AGGRO_STACK_FRACTION": 0.50,
        },
        "r15v fold QQ vs Nit/TAG extreme 50% stack",
    ),
    "r15v-fold-ak-vs-nit-tag-50": (
        [
            "FOLD_PREMIUM_VS_EXTREME_AGGRO",
            "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO",
            "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD",
            "EXTREME_AGGRO_STACK_FRACTION",
        ],
        {
            "FOLD_PREMIUM_VS_EXTREME_AGGRO": True,
            "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO": {"AKs", "AKo"},
            "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD": {"Nit", "TAG"},
            "EXTREME_AGGRO_STACK_FRACTION": 0.50,
        },
        "r15v fold AK vs Nit/TAG extreme 50% stack",
    ),
    "r15v-fold-qq-ak-vs-nit-50": (
        [
            "FOLD_PREMIUM_VS_EXTREME_AGGRO",
            "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO",
            "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD",
            "EXTREME_AGGRO_STACK_FRACTION",
        ],
        {
            "FOLD_PREMIUM_VS_EXTREME_AGGRO": True,
            "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO": {"QQ", "AKs", "AKo"},
            "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD": {"Nit"},
            "EXTREME_AGGRO_STACK_FRACTION": 0.50,
        },
        "r15v fold QQ/AK vs Nit extreme 50% stack",
    ),
    "r15v-fold-qq-ak-vs-nit-tag-75": (
        [
            "FOLD_PREMIUM_VS_EXTREME_AGGRO",
            "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO",
            "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD",
            "EXTREME_AGGRO_STACK_FRACTION",
        ],
        {
            "FOLD_PREMIUM_VS_EXTREME_AGGRO": True,
            "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO": {"QQ", "AKs", "AKo"},
            "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD": {"Nit", "TAG"},
            "EXTREME_AGGRO_STACK_FRACTION": 0.75,
        },
        "r15v fold QQ/AK vs Nit/TAG extreme 75% stack",
    ),
    "r16v-limp-behind-tight": (
        ["LIMP_BEHIND_OVER_LIMPERS", "LIMP_BEHIND_VPIP_MULTIPLIER"],
        {"LIMP_BEHIND_OVER_LIMPERS": True, "LIMP_BEHIND_VPIP_MULTIPLIER": 0.45},
        "r16v limp behind tight range",
    ),
    "r16v-limp-behind-medium": (
        ["LIMP_BEHIND_OVER_LIMPERS", "LIMP_BEHIND_VPIP_MULTIPLIER"],
        {"LIMP_BEHIND_OVER_LIMPERS": True, "LIMP_BEHIND_VPIP_MULTIPLIER": 0.55},
        "r16v limp behind medium range",
    ),
    "r16v-limp-behind-wide": (
        ["LIMP_BEHIND_OVER_LIMPERS", "LIMP_BEHIND_VPIP_MULTIPLIER"],
        {"LIMP_BEHIND_OVER_LIMPERS": True, "LIMP_BEHIND_VPIP_MULTIPLIER": 0.75},
        "r16v limp behind wide range",
    ),
    "r17v-call-by-raiser-position": (
        ["CALL_RANGE_BY_RAISER_POSITION"],
        {"CALL_RANGE_BY_RAISER_POSITION": True},
        "r17v call range by raiser position",
    ),
    "r18v-shove-aa-kk": (
        ["SHOVE_AA_KK_VS_3BET_PLUS", "SHOVE_VS_3BET_PLUS_RANGE"],
        {"SHOVE_AA_KK_VS_3BET_PLUS": True, "SHOVE_VS_3BET_PLUS_RANGE": {"AA", "KK"}},
        "r18v shove AA/KK vs 3bet+",
    ),
    "r18v-shove-qq-plus": (
        ["SHOVE_AA_KK_VS_3BET_PLUS", "SHOVE_VS_3BET_PLUS_RANGE"],
        {"SHOVE_AA_KK_VS_3BET_PLUS": True, "SHOVE_VS_3BET_PLUS_RANGE": {"AA", "KK", "QQ"}},
        "r18v shove QQ+ vs 3bet+",
    ),
    "r18v-shove-qq-ak": (
        ["SHOVE_AA_KK_VS_3BET_PLUS", "SHOVE_VS_3BET_PLUS_RANGE"],
        {"SHOVE_AA_KK_VS_3BET_PLUS": True, "SHOVE_VS_3BET_PLUS_RANGE": {"AA", "KK", "QQ", "AKs", "AKo"}},
        "r18v shove QQ+/AK vs 3bet+",
    ),
    "r19v-bb-defend-minraise-tight": (
        ["BB_DEFEND_VS_STEAL_MINRAISE", "BB_DEFEND_MAX_RAISE_BB", "BB_DEFEND_VPIP_MULTIPLIER"],
        {"BB_DEFEND_VS_STEAL_MINRAISE": True, "BB_DEFEND_MAX_RAISE_BB": 2.0, "BB_DEFEND_VPIP_MULTIPLIER": 1.3},
        "r19v BB defend vs minraise tight",
    ),
    "r19v-bb-defend-steal-medium": (
        ["BB_DEFEND_VS_STEAL_MINRAISE", "BB_DEFEND_MAX_RAISE_BB", "BB_DEFEND_VPIP_MULTIPLIER"],
        {"BB_DEFEND_VS_STEAL_MINRAISE": True, "BB_DEFEND_MAX_RAISE_BB": 2.5, "BB_DEFEND_VPIP_MULTIPLIER": 1.6},
        "r19v BB defend vs steal medium",
    ),
    "r19v-bb-defend-steal-wide": (
        ["BB_DEFEND_VS_STEAL_MINRAISE", "BB_DEFEND_MAX_RAISE_BB", "BB_DEFEND_VPIP_MULTIPLIER"],
        {"BB_DEFEND_VS_STEAL_MINRAISE": True, "BB_DEFEND_MAX_RAISE_BB": 2.5, "BB_DEFEND_VPIP_MULTIPLIER": 2.0},
        "r19v BB defend vs steal wide",
    ),
    "v30v-mild-narrow": (
        ["SIZE_SCALED_CALL_RANGE", "CALL_VPIP_NARROW_MULTIPLIER"],
        {"SIZE_SCALED_CALL_RANGE": True, "CALL_VPIP_NARROW_MULTIPLIER": 0.85},
        "v30v size-scaled call, milder narrow (0.85x vs current 0.7x)",
    ),
    "v30v-no-narrow": (
        ["SIZE_SCALED_CALL_RANGE", "CALL_VPIP_NARROW_MULTIPLIER"],
        {"SIZE_SCALED_CALL_RANGE": True, "CALL_VPIP_NARROW_MULTIPLIER": 1.0},
        "v30v size-scaled call, widen-only (narrow tier == base range, never actually narrows)",
    ),
    "v30v-mild-both": (
        ["SIZE_SCALED_CALL_RANGE", "CALL_VPIP_WIDE_MULTIPLIER", "CALL_VPIP_NARROW_MULTIPLIER"],
        {"SIZE_SCALED_CALL_RANGE": True, "CALL_VPIP_WIDE_MULTIPLIER": 1.15, "CALL_VPIP_NARROW_MULTIPLIER": 0.85},
        "v30v size-scaled call, milder both tiers (1.15x/0.85x vs current 1.3x/0.7x)",
    ),
    # 2026-08-17, follow-up round: user asked to re-test SB_BIGGER_OPEN_SIZING
    # at 3.5bb specifically -- the already-tested 3.0bb step (inconclusive,
    # +0.19/+0.04) might have been too small to move the needle. Baseline
    # here is the real current default (SB_BIGGER_OPEN_SIZING=False, i.e.
    # flat 2.5bb), same as the original 3.0bb test.
    "sb-open-3.5bb": (
        ["SB_BIGGER_OPEN_SIZING", "SB_OPEN_SIZING_BB"],
        {"SB_BIGGER_OPEN_SIZING": True, "SB_OPEN_SIZING_BB": 3.5},
        "SB open to 3.5bb instead of 2.5bb, blind-vs-blind only",
    ),
    # 2026-08-17: real head-to-head between the two limper-isolation
    # mechanisms. Found while explaining the code that ISO_WIDER_RANGE_OVER_
    # LIMPERS is currently structurally dead -- TIGHT_BIG_ISO_RAISE_LIMPERS
    # is unconditional on n_limpers>=1 (no hand-set gate), so it always wins
    # and ISO_WIDER's own branch (`not use_tight_big_iso`) can never fire.
    # Baseline = today's actual live default (both True in the file, but
    # TIGHT_BIG_ISO wins in practice). Treatment = flip which one is
    # actually live, so this measures TIGHT_BIG_ISO (narrower range, much
    # bigger sizing) against ISO_WIDER (wider range, normal sizing) directly
    # against each other, not against "no isolation change" like their
    # original individual confirmations did.
    "tight-iso-vs-wide-iso-headtohead": (
        ["TIGHT_BIG_ISO_RAISE_LIMPERS", "ISO_WIDER_RANGE_OVER_LIMPERS"],
        {"TIGHT_BIG_ISO_RAISE_LIMPERS": False, "ISO_WIDER_RANGE_OVER_LIMPERS": True},
        "ISO_WIDER_RANGE_OVER_LIMPERS live instead of TIGHT_BIG_ISO_RAISE_LIMPERS (today's actual default)",
    ),
}

PARAMETER_VARIANT_GROUPS = {
    name: (flags, label) for name, (flags, _treatment, label) in PARAMETER_VARIANTS.items()
}


def _all_test_groups() -> dict[str, tuple[list[str], str]]:
    return {
        **PRESET_FLAG_GROUPS,
        **EXTRA_TEST_GROUPS,
        **RULE_TEST_GROUPS,
        **TIGHT_ISO_VARIANT_GROUPS,
        **PARAMETER_VARIANT_GROUPS,
    }


PSEUDO_OPPONENT_AWARE = "OPPONENT_AWARE_ARCHETYPES"
PSEUDO_FLAGS = {PSEUDO_OPPONENT_AWARE}
MULTIWAY_SUBFLAGS = {"MULTIWAY_NARROW_CALL_RANGE", "MULTIWAY_DISABLE_AIR_CBET", "MULTIWAY_DISABLE_LOOSE_CALL"}

ALL_COMPARISON_FLAGS = [
    "ALLOW_CALLING_RAISES",
    "UNCONDITIONAL_FLOP_CBET",
    "USE_WIDE_VALUE_3BET",
    "STEAL_WIDER_VS_NIT",
    "SIZING_TARGET_ARCHETYPES",
    "WIDER_3BET_VS_LOOSE",
    "SIZE_UP_ON_TURN",
    "ISO_RAISE_OVER_LIMPERS",
    "TIGHT_BIG_ISO_RAISE_LIMPERS",
    "TIGHT_ISO_VPIP_MULTIPLIER",
    "TIGHT_ISO_BASE_SIZING_BB",
    "TIGHT_ISO_SIZING_PER_LIMPER_BB",
    "DONK_BLUFF_VS_TIGHT",
    "HERO_PROGRESSIVE_POT_DAMPING",
    "SQUEEZE_WIDER_RANGE",
    "SQUEEZE_SIZE_UP_PER_CALLER",
    "VALUE_RAISE_FACING_BET",
    "VALUE_RAISE_TRIPS_OR_BETTER_ONLY",
    "FOLD_TOP_PAIR_VS_OVERBET",
    "SIZE_UP_WITH_VERY_STRONG_HAND",
    "SIZE_UP_ON_WET_BOARD",
    "SMALLER_BLUFF_ON_WET_BOARD",
    "BLUFF_3BET_VS_TIGHT",
    "BLUFF_3BET_TARGET_ARCHETYPES",
    "BARREL_BLUFF_VS_TIGHT",
    "FOLD_PREMIUM_VS_EXTREME_AGGRO",
    "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO",
    "TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD",
    "EXTREME_AGGRO_STACK_FRACTION",
    "RIVER_OVERBET_NUTS_VS_LOOSE",
    "TURN_OVERBET_NUTS_VS_LOOSE",
    "OPTIMAL_VALUE_SIZING_PER_ARCHETYPE",
    "ISO_WIDER_RANGE_OVER_LIMPERS",
    "SIZE_SCALED_CALL_RANGE",
    "SHOVE_AA_KK_VS_3BET_PLUS",
    "SHOVE_VS_3BET_PLUS_RANGE",
    "LIMP_BEHIND_OVER_LIMPERS",
    "LIMP_BEHIND_VPIP_MULTIPLIER",
    "CALL_RANGE_BY_RAISER_POSITION",
    "SIZE_UP_PREMIUM_OPENS",
    "TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR",
    "CALL_VPIP_WIDE_MULTIPLIER",
    "CALL_VPIP_NARROW_MULTIPLIER",
    "SMALL_RAISE_BB_THRESHOLD",
    "BIG_RAISE_BB_THRESHOLD",
    "BB_DEFEND_VS_STEAL_MINRAISE",
    "BB_DEFEND_MAX_RAISE_BB",
    "BB_DEFEND_VPIP_MULTIPLIER",
    "BB_DEFEND_MDF_SCALED",
    "BB_DEFEND_MDF_TRIGGER",
    "RAKE_ADJUSTED_OPEN_SIZING",
    "RAKE_ADJUSTED_OPEN_SIZING_BB",
    "THREEBET_SIZE_BY_POSITION",
    "THREEBET_MULTIPLIER_IP",
    "THREEBET_MULTIPLIER_OOP",
    "BLUFF_3BET_BLOCKER_RANGE_FLAG",
    "THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT",
    "FOLD_VS_3BET_FROM_PASSIVE",
    "LIMP_TRAP_WITH_MONSTERS",
    "LIMP_TRAP_FREQUENCY",
    "SET_MINE_IMPLIED_ODDS",
    "SIZED_4BET_INSTEAD_OF_SHOVE",
    "SIZED_4BET_MULTIPLIER_IP",
    "SIZED_4BET_MULTIPLIER_OOP",
    "SB_BIGGER_OPEN_SIZING",
    "SB_OPEN_SIZING_BB",
    "SB_THREEBET_OR_FOLD_VS_STEAL",
    "FOLD_MARGINAL_VS_CHECK_RAISE",
    "FLOAT_FLOP_IN_POSITION",
    "FLOAT_FOLLOWUP_POT_FRACTION",
    "FOLD_MARGINAL_VS_BIG_DONK",
    "BIG_DONK_POT_FRACTION",
    "FOLD_TOP_PAIR_VS_WET_BOARD_TIGHT",
    "RIVER_BLUFF_MISSED_DRAW",
    "RIVER_BLUFF_MISSED_DRAW_POT_FRACTION",
    "WIDER_CALL_VS_OFTEN_TIER",
    "FLOAT_TURN_IN_POSITION",
    "SIZE_UP_PREMIUM_3BETS",
    "WIDER_CALL_VS_TILTING_OPPONENT",
    "BLUFF_CATCH_VS_FREQUENT_BLUFFER_A",
    "BLUFF_CATCH_VS_FREQUENT_BLUFFER_C",
    *sorted(MULTIWAY_SUBFLAGS),
]

HISTORICAL_PRIOR_ON_FLAGS = {
    "v11-multiway-aware": ["USE_WIDE_VALUE_3BET"],
    "v14-steal-sizing": ["USE_WIDE_VALUE_3BET"],
    "v15-loose-3bet-turn": ["USE_WIDE_VALUE_3BET", "STEAL_WIDER_VS_NIT", "SIZING_TARGET_ARCHETYPES"],
    "v16-iso-limpers": [
        "USE_WIDE_VALUE_3BET",
        "STEAL_WIDER_VS_NIT",
        "SIZING_TARGET_ARCHETYPES",
        "WIDER_3BET_VS_LOOSE",
        "SIZE_UP_ON_TURN",
    ],
    "v17-donk-bluff": [
        "USE_WIDE_VALUE_3BET",
        "STEAL_WIDER_VS_NIT",
        "SIZING_TARGET_ARCHETYPES",
        "WIDER_3BET_VS_LOOSE",
        "SIZE_UP_ON_TURN",
        "ISO_RAISE_OVER_LIMPERS",
    ],
    # v21+ happened after the monster-pot damping work. Squeeze itself stays
    # off in later historical baselines: the changelog says it was not
    # confirmed and shipped off, even if today's module default drifts.
    #
    # 2026-08-12 BUG FOUND AND FIXED: this list was missing ALLOW_CALLING_
    # RAISES (v3) and UNCONDITIONAL_FLOP_CBET (v6) -- both foundational,
    # confirmed-real rules shipped True LONG before v21 (v3: the "raise-or-
    # fold-only" leak fix; v6: -1.11 vs -9.90 bb/100 without rake, one of
    # the earliest confirmed deltas in the whole file). _historical_baseline_
    # state resets EVERY flag in ALL_COMPARISON_FLAGS to False except what's
    # explicitly listed here -- so every "historical"-mode v21-v30 test run
    # BEFORE this fix had hero permanently unable to call a facing raise
    # (fold-or-3bet-only) and never c-betting the flop with air, a severely
    # crippled baseline that doesn't represent "today's actual strategy" at
    # all. Found while root-causing why v30 (SIZE_SCALED_CALL_RANGE) showed
    # zero divergent hands even after its thresholds were correctly
    # recalibrated: a specific hand (JTo, SB, facing a 3.25bb raise) that
    # should have called in baseline (in call_ranges[SB]) instead folded in
    # BOTH baseline and treatment, because ALLOW_CALLING_RAISES=False made
    # the entire call-range branch unreachable regardless of the flag under
    # test. Every v22-v30 "historical" result reported earlier tonight
    # needs to be treated as suspect and re-run with this fix -- see
    # CLAUDE.md's "historical baseline bug" note for which ones actually
    # changed after re-running.
    "v21-squeeze-wide": [
        "ALLOW_CALLING_RAISES",
        "UNCONDITIONAL_FLOP_CBET",
        "USE_WIDE_VALUE_3BET",
        "STEAL_WIDER_VS_NIT",
        "SIZING_TARGET_ARCHETYPES",
        "WIDER_3BET_VS_LOOSE",
        "SIZE_UP_ON_TURN",
        "ISO_RAISE_OVER_LIMPERS",
        "DONK_BLUFF_VS_TIGHT",
        "HERO_PROGRESSIVE_POT_DAMPING",
    ],
}
HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-size"] = HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-wide"]
HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-both"] = HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-wide"]

for _preset in (
    "v22-value-raise",
    "v22-value-raise-trips",
    "v23-overbet-fold",
    "v23-size-strong",
    "v23-size-wet",
    "v23-size-both",
    "v24-bluff-3bet",
    "v25-barrel-bluff",
    "v26-fold-premium-extreme",
    "v27-river-overbet",
    "v28-optimal-sizing",
    "v29-iso-wider-range",
    "v30-size-scaled-call",
):
    HISTORICAL_PRIOR_ON_FLAGS[_preset] = HISTORICAL_PRIOR_ON_FLAGS["v21-squeeze-wide"]


@dataclass(frozen=True)
class ProbeComparison:
    label: str
    baseline: dict[str, object]
    treatment: dict[str, object]


def _real_flag_value(name: str, value: bool) -> object:
    if name in PSEUDO_FLAGS:
        return value
    if name in _NON_BOOLEAN_FLAG_ON_VALUES:
        return _NON_BOOLEAN_FLAG_ON_VALUES[name] if value else _NON_BOOLEAN_FLAG_OFF_VALUES[name]
    return value


def _state_for_flags(flag_names: list[str], value: bool) -> dict[str, object]:
    return {name: _real_flag_value(name, value) for name in flag_names}


def _current_state_for_flags(flag_names: list[str]) -> dict[str, object]:
    state = {}
    for name in flag_names:
        if name == PSEUDO_OPPONENT_AWARE:
            state[name] = True
        else:
            value = getattr(abc_bot, name)
            state[name] = set(value) if name in _NON_BOOLEAN_FLAG_ON_VALUES else value
    return state


def _historical_baseline_state(preset: str) -> dict[str, object]:
    if preset == "v9-wide-3bet":
        raise ValueError(
            "v9 predates the v10 opponent-aware calling rule, but this probe always runs with "
            "opponent archetypes. Use --comparison current for v9, or add an explicit opponent-aware off arm."
        )
    if preset not in HISTORICAL_PRIOR_ON_FLAGS:
        raise ValueError(f"no historical comparison profile for {preset}")
    state = {name: _real_flag_value(name, False) for name in ALL_COMPARISON_FLAGS}
    for name in HISTORICAL_PRIOR_ON_FLAGS[preset]:
        state[name] = _real_flag_value(name, True)
    return state


def _build_comparison(preset: str, comparison: Literal["current", "historical", "ablation"]) -> ProbeComparison:
    flag_names, _ = _all_test_groups()[preset]
    if preset == "sb-flat-call-vs-fold-diagnostic":
        if comparison != "current":
            raise ValueError("sb-flat-call-vs-fold-diagnostic only supports --comparison current")
        # Both arms force SB_THREEBET_OR_FOLD_VS_STEAL off (unlike
        # _current_state_for_flags, which would pick up its real shipped
        # True value) so the call-range branch is actually reachable in
        # both arms -- only SB_FOLD_VS_STEAL_DIAGNOSTIC varies.
        baseline = {"SB_THREEBET_OR_FOLD_VS_STEAL": False, "SB_FOLD_VS_STEAL_DIAGNOSTIC": False}
        treatment = {"SB_THREEBET_OR_FOLD_VS_STEAL": False, "SB_FOLD_VS_STEAL_DIAGNOSTIC": True}
        return ProbeComparison("SB flat-call range vs fold, both vs a steal (3-bet-or-fold forced off both arms)", baseline, treatment)
    if preset in TIGHT_ISO_VARIANTS:
        if comparison != "current":
            raise ValueError("tight iso parameter variants only support --comparison current")
        mult, base, per_limper = TIGHT_ISO_VARIANTS[preset]
        baseline = _current_state_for_flags(TIGHT_ISO_PARAM_FLAGS)
        baseline["TIGHT_BIG_ISO_RAISE_LIMPERS"] = True
        treatment = baseline | {
            "TIGHT_BIG_ISO_RAISE_LIMPERS": True,
            "TIGHT_ISO_VPIP_MULTIPLIER": mult,
            "TIGHT_ISO_BASE_SIZING_BB": base,
            "TIGHT_ISO_SIZING_PER_LIMPER_BB": per_limper,
        }
        return ProbeComparison("tight iso parameter variant - current r12", baseline, treatment)
    if preset in PARAMETER_VARIANTS:
        if comparison != "current":
            raise ValueError("parameter variants only support --comparison current")
        flags, treatment_overlay, _label = PARAMETER_VARIANTS[preset]
        baseline = _current_state_for_flags(flags)
        treatment = baseline | treatment_overlay
        return ProbeComparison("parameter variant - current defaults", baseline, treatment)
    if comparison == "current":
        return ProbeComparison(
            "current defaults overlay",
            _state_for_flags(flag_names, False),
            _state_for_flags(flag_names, True),
        )
    if comparison == "ablation":
        baseline = _current_state_for_flags(flag_names)
        treatment = baseline | _state_for_flags(flag_names, False)
        return ProbeComparison("current full-model ablation (without rule - full)", baseline, treatment)
    baseline = _historical_baseline_state(preset)
    treatment = baseline | _state_for_flags(flag_names, True)
    return ProbeComparison("historical at-introduction flags", baseline, treatment)


def _invalidate_cached_ranges_if_needed(state: dict[str, object]) -> None:
    if {"TIGHT_ISO_VPIP_MULTIPLIER", "TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR"} & state.keys():
        abc_bot._tight_iso_range_cache = {}
    if {"TIGHT_ISO_TIGHTENS_PER_EXTRA_LIMPER", "TIGHT_ISO_EXTRA_LIMPER_STEP"} & state.keys():
        abc_bot._tight_iso_range_by_limpers_cache = {}
    if "LIMP_BEHIND_VPIP_MULTIPLIER" in state:
        abc_bot._limp_behind_range_cache = {}
    if "BB_DEFEND_VPIP_MULTIPLIER" in state:
        abc_bot._bb_defend_range_cache = {}
    if {"CALL_VPIP_WIDE_MULTIPLIER"} & state.keys():
        abc_bot._call_range_wide_cache = {}
    if {"CALL_VPIP_NARROW_MULTIPLIER"} & state.keys():
        abc_bot._call_range_narrow_cache = {}


def _apply_flag_state(state: dict[str, object]) -> None:
    for name, real_value in state.items():
        if name in PSEUDO_FLAGS:
            continue
        if name in _NON_BOOLEAN_FLAG_ON_VALUES:
            real_value = set(real_value)
        setattr(abc_bot, name, real_value)
    _invalidate_cached_ranges_if_needed(state)
    if "USE_WIDE_VALUE_3BET" in state:
        _sync_value_3bet(bool(state["USE_WIDE_VALUE_3BET"]))
    if MULTIWAY_SUBFLAGS & state.keys() and "MULTIWAY_AWARE" not in state:
        abc_bot.MULTIWAY_AWARE = any(bool(getattr(abc_bot, name)) for name in MULTIWAY_SUBFLAGS)


def _restore_flags(original: dict[str, object]) -> None:
    for name, value in original.items():
        if name in PSEUDO_FLAGS:
            continue
        setattr(abc_bot, name, value)
    _invalidate_cached_ranges_if_needed(original)
    if "USE_WIDE_VALUE_3BET" in original:
        _sync_value_3bet(original["USE_WIDE_VALUE_3BET"])
    if MULTIWAY_SUBFLAGS & original.keys() and "MULTIWAY_AWARE" not in original:
        abc_bot.MULTIWAY_AWARE = any(bool(getattr(abc_bot, name)) for name in MULTIWAY_SUBFLAGS)


def _make_table() -> Table:
    table = Table(
        small_blind=1.0,
        big_blind=2.0,
        max_seats=MAX_SEATS,
        rake_percent=RAKE_PERCENT,
        rake_cap_bb=RAKE_CAP_BB,
    )
    for seat in range(1, MAX_SEATS + 1):
        table.add_player(seat=seat, name=("Hero" if seat == HERO_SEAT else f"Bot{seat}"), stack=STARTING_STACK)
    return table


def _reset_stacks(table: Table) -> None:
    for player in table.players.values():
        player.stack = STARTING_STACK
        player.sitting_out = False


def _hero_net(hand) -> float:
    invested = hand.players[HERO_SEAT].total_contributed
    payout = hand.result.payouts.get(HERO_SEAT, 0.0) if hand.result else 0.0
    return payout - invested


def _force_next_board_card(hand, card_str: str) -> bool:
    if hand.finished or len(hand.board) >= 5:
        return False
    for i, card in enumerate(hand.deck.cards):
        if str(card) == card_str:
            chosen = hand.deck.cards.pop(i)
            hand.deck.cards.insert(0, chosen)
            return True
    return False


def _pick_hero_hand_swap(
    hand, notations: set[str], hand_index: int, base_seed: int = 42, seat: int = HERO_SEAT,
    seed_stream: int = HERO_HAND_SEED_STREAM,
) -> tuple[list[str], list[str]] | None:
    """Finds a replacement for `seat`'s already-dealt hole cards matching one
    of `notations` (e.g. {"QQ","AKs","AKo"}), sourced from hand.deck.cards
    (the remaining, undealt pool) -- same swap principle as
    _force_next_board_card, applied to hole cards instead of the board.
    Returns (new_hole_card_strs, old_hole_card_strs) without mutating
    anything, so the identical swap (same exact card strings) can be applied
    to both the baseline and treatment hand for a valid paired comparison.
    Returns None if no card in the remaining deck can complete any of the
    target notations (rare, but possible once enough cards are already
    dealt to other seats). Deterministic per hand_index (own seed stream,
    common-random-numbers discipline like every other draw in this file) --
    NOT the bare global `random` module, which would make reruns
    unreproducible. `seat`/`seed_stream` default to hero's own -- pass a
    different seat (and a different seed_stream, so the draw doesn't
    coincide with hero's own hand-forcing draw) to condition an OPPONENT's
    hand instead, e.g. forcing a realistic reraising range onto whichever
    seat force_opponent_reraise makes reraise."""
    rng = random.Random(_common_seed(base_seed, hand_index, seed_stream))
    remaining = hand.deck.cards
    for notation in rng.sample(sorted(notations), len(notations)):
        if len(notation) == 2:  # pocket pair, e.g. "QQ"
            rank = notation[0]
            candidates = [c for c in remaining if c.rank == rank]
            if len(candidates) >= 2:
                chosen = rng.sample(candidates, 2)
                return [str(c) for c in chosen], list(hand.players[seat].hole_cards)
            continue
        r1, r2, suited = notation[0], notation[1], notation[2] == "s"
        pairs = []
        for c1 in remaining:
            if c1.rank != r1:
                continue
            for c2 in remaining:
                if c2.rank != r2 or c2 is c1:
                    continue
                if suited and c1.suit != c2.suit:
                    continue
                if not suited and c1.suit == c2.suit:
                    continue
                pairs.append((c1, c2))
        if pairs:
            chosen = rng.choice(pairs)
            return [str(c) for c in chosen], list(hand.players[seat].hole_cards)
    return None


def _apply_hero_hand_swap(hand, new_cards: list[str], old_cards: list[str], seat: int = HERO_SEAT) -> None:
    """Applies an EXACT swap (by card string) computed elsewhere -- used to
    mirror the same forced hand onto both the baseline and treatment Hand
    objects, which are dealt from the same deck_seed and so have identical
    remaining decks at this point. `seat` defaults to hero's own; pass a
    different seat to apply an opponent's forced hand instead."""
    remaining = hand.deck.cards
    for card_str in new_cards:
        for i, card in enumerate(remaining):
            if str(card) == card_str:
                remaining.pop(i)
                break
    hand.players[seat].hole_cards = list(new_cards)
    remaining.extend(Card(c) for c in old_cards)


def _available_next_cards(*hands) -> list[str]:
    for hand in hands:
        if not hand.finished and len(hand.board) < 5:
            return [str(card) for card in hand.deck.cards]
    return []


def _hero_opponent_archetypes(hand, turnover: TableTurnover, flag_state: dict[str, object]) -> dict[int, str] | None:
    if flag_state.get(PSEUDO_OPPONENT_AWARE, True) is False:
        return None
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    return {s: turnover.archetype_for(s) for s in bot_seats if hand.players[s].in_hand}


def _hero_opponent_freq_tiers(hand, turnover: TableTurnover) -> dict[int, str] | None:
    """Ground-truth {seat: postflop_freq_tier}, unconditional -- unlike
    opponent_archetypes above, there's no PSEUDO_OPPONENT_AWARE gate yet
    because no preset/rule reads this axis yet (2026-08-20 infra-only
    step). Wired here so a future freq-tier-aware preset doesn't need any
    further plumbing, just a comparison branch in _build_comparison that
    reads opponent_freq_tiers. Note the seated bots' actual behavior does
    NOT vary by this tier yet -- the ML opponent model wasn't retrained
    with it as a feature, so this is ground truth for a signal the
    opponents don't yet act on."""
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    return {s: turnover.freq_tier_for(s) for s in bot_seats if hand.players[s].in_hand}


def _hero_opponent_tilt_states_sampled(hand, hand_index: int, base_seed: int) -> dict[int, str] | None:
    """LEGACY (2026-08-21 first attempt, superseded by the live version
    below once _run_probe_chunk started calling record_hand_for_tilt()):
    ground-truth {seat: tilt_tier}, sampled independently per hand per
    opponent from TILT_TIER_WEIGHTS (see that constant's comment) instead
    of read from real accumulated history. Kept only so the
    wider-call-vs-tilting-opponent result already recorded in abc_bot.py's
    changelog (seed42 confirmed_positive +0.70, seed777 zero divergent)
    stays reproducible from this file -- not called by anything anymore."""
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    tiers = list(TILT_TIER_WEIGHTS.keys())
    weights = list(TILT_TIER_WEIGHTS.values())
    out = {}
    for s in bot_seats:
        if not hand.players[s].in_hand:
            continue
        rng = random.Random(_common_seed(base_seed, hand_index, TILT_SEED_STREAM, s))
        out[s] = rng.choices(tiers, weights=weights)[0]
    return out


def _hero_opponent_tilt_states(hand, turnover: TableTurnover) -> dict[int, str] | None:
    """Ground-truth {seat: tilt_tier}, read from TableTurnover's real
    accumulated hand-to-hand history (see record_hand_for_tilt, now called
    once per genuinely-finished hand in _run_probe_chunk's main loop) --
    a real cooler must actually have occurred in a preceding hand of THIS
    probe run for a seat to read as anything but "none" here. Same shape
    as _hero_opponent_freq_tiers above."""
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    out = {}
    for s in bot_seats:
        if not hand.players[s].in_hand:
            continue
        out[s] = turnover.tilt_tier_for(s)
    return out


def _hero_opponent_bluff_tiers(hand, turnover: TableTurnover, variant: str) -> dict[int, str] | None:
    """Ground-truth {seat: bluff_tier}, static per-seat label like
    archetype/freq_tier (not dynamic like tilt) -- `variant` is "a" or "c",
    see BLUFF_TIER_A_WEIGHTS/BLUFF_TIER_C_WEIGHTS comment in
    live_dynamics.py for what they mean."""
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    getter = turnover.bluff_tier_a_for if variant == "a" else turnover.bluff_tier_c_for
    return {s: getter(s) for s in bot_seats if hand.players[s].in_hand}


def _should_force_opponent_reraise(hand, seat: int) -> bool:
    """True when `seat` (a non-hero seat) is facing exactly hero's own
    preflop raise -- i.e. this is the decision point where "does the
    opponent re-raise (3-bet/4-bet+) hero" would happen. Used by
    force_opponent_reraise to condition rules like r13/v26/r15v-fold-*/
    r18v-shove-* that only fire once hero is FACING a re-raise, a spot
    this population reaches too rarely on its own (barely 3-bets at all --
    see BLUFF_3BET_VS_TIGHT's own motivation) for natural incidence to
    ever surface enough observations, even across hundreds of thousands
    of hands.

    Fires AT MOST ONCE per hand (only when hero's raise is the exact
    FIRST preflop raise) -- without this guard, a forced reraise puts
    "hero's raise" back on top again after hero's own next action (a
    3-bet/shove response), which would keep matching this same condition
    and cascade into an unbounded, unrealistic raise war (confirmed: an
    early version of this function reached 7 preflop raises in one hand
    before the guard was added)."""
    if hand.street != "preflop" or hand.finished:
        return False
    preflop = [a for a in hand.actions if a.street == "preflop"]
    if not preflop or preflop[-1].action != "raises" or preflop[-1].seat != HERO_SEAT:
        return False
    n_raises = sum(1 for a in preflop if a.action == "raises")
    if n_raises != 1:
        return False
    return hand.current_actor() == seat


# 2026-08-13: a first version of force_opponent_reraise forced the ACTION
# only, leaving the opponent's actual dealt cards untouched -- this creates
# an artificially wide/weak "reraising range" (any random hand forced to
# reraise, not a real hand-selected one), and hero's forced premium hand
# crushed it far harder than it would a real opponent range (a smoke test
# measured deltas in the THOUSANDS of bb/100, clearly not real -- see
# CLAUDE.md's "r13/v26/..." section for the full story). Fixed by ALSO
# forcing the reraiser's cards to a real 3-betting-tier range
# (VALUE_3BET_WIDE: AA/KK/QQ/JJ/TT/AKs/AKo/AQs/AQo) -- not a perfect
# per-archetype reraising range, but a real, standard-theory "hand strong
# enough to 4-bet with" set, not an arbitrary one.
OPPONENT_RERAISE_HAND_SET = abc_bot.VALUE_3BET_WIDE


def _force_reraise_action(
    hand, seat: int, hand_index: int, base_seed: int = 42
) -> tuple[str, float | None]:
    swap = _pick_hero_hand_swap(
        hand, OPPONENT_RERAISE_HAND_SET, hand_index, base_seed, seat, OPPONENT_HAND_SEED_STREAM
    )
    if swap is not None:
        new_cards, old_cards = swap
        _apply_hero_hand_swap(hand, new_cards, old_cards, seat)
    legal = hand.legal_actions(seat)
    amount = legal["min_raise_to"]
    return "raise", amount


def _choose_and_apply(
    hand,
    seat: int,
    hand_index: int,
    guard: int,
    turnover: TableTurnover,
    flag_state: dict[str, object],
    base_seed: int = 42,
    force_opponent_reraise: bool = False,
) -> tuple[str, float | None]:
    if seat == HERO_SEAT:
        _apply_flag_state(flag_state)
        opponent_archetypes = _hero_opponent_archetypes(hand, turnover, flag_state)
        opponent_freq_tiers = _hero_opponent_freq_tiers(hand, turnover)
        opponent_tilt_states = _hero_opponent_tilt_states(hand, turnover)
        opponent_bluff_tiers_a = _hero_opponent_bluff_tiers(hand, turnover, "a")
        opponent_bluff_tiers_c = _hero_opponent_bluff_tiers(hand, turnover, "c")
        action, amount = choose_abc_action(
            hand,
            seat,
            opponent_archetypes=opponent_archetypes,
            opponent_freq_tiers=opponent_freq_tiers,
            opponent_tilt_states=opponent_tilt_states,
            opponent_bluff_tiers_a=opponent_bluff_tiers_a,
            opponent_bluff_tiers_c=opponent_bluff_tiers_c,
        )
    elif force_opponent_reraise and _should_force_opponent_reraise(hand, seat):
        action, amount = _force_reraise_action(hand, seat, hand_index, base_seed)
    else:
        archetype = turnover.archetype_for(seat)
        freq_tier = turnover.freq_tier_for(seat)
        tilt_tier = turnover.tilt_tier_for(seat)
        bluff_tier_a = turnover.bluff_tier_a_for(seat)
        bluff_tier_c = turnover.bluff_tier_c_for(seat)
        bot_seed = _common_seed(base_seed, hand_index, BOT_ACTION_SEED_STREAM, guard, seat)
        action, amount = choose_bot_action(
            hand,
            seat,
            archetype=archetype,
            freq_tier=freq_tier,
            tilt_tier=tilt_tier,
            bluff_tier_a=bluff_tier_a,
            bluff_tier_c=bluff_tier_c,
            seed=bot_seed,
        )

    try:
        hand.apply_action(seat, action, amount)
    except IllegalAction:
        action, amount = "fold", None
        hand.apply_action(seat, "fold")
    return action, amount


def _continue_to_finish(
    hand,
    hand_index: int,
    turnover: TableTurnover,
    flag_state: dict[str, object],
    branch_id: int = 0,
    base_seed: int = 42,
) -> float | None:
    guard = 0
    while not hand.finished and guard < 500:
        seat = hand.current_actor()
        if seat is None:
            break
        if seat == HERO_SEAT:
            _apply_flag_state(flag_state)
            opponent_archetypes = _hero_opponent_archetypes(hand, turnover, flag_state)
            opponent_freq_tiers = _hero_opponent_freq_tiers(hand, turnover)
            opponent_tilt_states = _hero_opponent_tilt_states(hand, turnover)
            opponent_bluff_tiers_a = _hero_opponent_bluff_tiers(hand, turnover, "a")
            opponent_bluff_tiers_c = _hero_opponent_bluff_tiers(hand, turnover, "c")
            action, amount = choose_abc_action(
                hand,
                seat,
                opponent_archetypes=opponent_archetypes,
                opponent_freq_tiers=opponent_freq_tiers,
                opponent_tilt_states=opponent_tilt_states,
                opponent_bluff_tiers_a=opponent_bluff_tiers_a,
                opponent_bluff_tiers_c=opponent_bluff_tiers_c,
            )
        else:
            archetype = turnover.archetype_for(seat)
            freq_tier = turnover.freq_tier_for(seat)
            tilt_tier = turnover.tilt_tier_for(seat)
            bluff_tier_a = turnover.bluff_tier_a_for(seat)
            bluff_tier_c = turnover.bluff_tier_c_for(seat)
            bot_seed = _common_seed(base_seed, hand_index, BOT_ACTION_SEED_STREAM, guard, seat, branch_id)
            action, amount = choose_bot_action(
                hand,
                seat,
                archetype=archetype,
                freq_tier=freq_tier,
                tilt_tier=tilt_tier,
                bluff_tier_a=bluff_tier_a,
                bluff_tier_c=bluff_tier_c,
                seed=bot_seed,
            )
        try:
            hand.apply_action(seat, action, amount)
        except IllegalAction:
            hand.apply_action(seat, "fold")
        guard += 1
    return _hero_net(hand) if hand.finished else None


def _stats(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    ci = 1.96 * stdev / (len(values) ** 0.5) * 100 if len(values) > 1 else 0.0
    return mean * 100, ci


def _run_probe_chunk(
    baseline_state: dict[str, object],
    treatment_state: dict[str, object],
    base_table: Table,
    treat_table: Table,
    base_turnover: TableTurnover,
    treat_turnover: TableTurnover,
    start_hand_index: int,
    n_hands: int,
    random_deltas: list[float],
    enum_deltas: list[float],
    branch_counts: list[int],
    hero_hand_filter: set[str] | None = None,
    base_seed: int = 42,
    force_opponent_reraise: bool = False,
) -> int:
    divergent = 0
    for hand_index in range(start_hand_index, start_hand_index + n_hands):
        _reset_stacks(base_table)
        _reset_stacks(treat_table)
        deck_seed = _common_seed(base_seed, hand_index, DECK_SEED_STREAM)
        base_hand = base_table.start_new_hand(deck_seed=deck_seed)
        treat_hand = treat_table.start_new_hand(deck_seed=deck_seed)

        if hero_hand_filter:  # falsy for both None (unset) and an explicit empty set (opt-out)
            # Force hero's dealt hand to one of the target notations instead
            # of waiting for natural incidence (e.g. QQ+/AK is ~1.8% of
            # hands -- a rule that only ever fires there would need >50k
            # hands just to see a handful of real observations). Base and
            # treatment get the IDENTICAL forced cards (both dealt from the
            # same deck_seed, so their pre-swap decks match exactly) --
            # otherwise this wouldn't be a valid paired comparison anymore.
            swap = _pick_hero_hand_swap(base_hand, hero_hand_filter, hand_index, base_seed)
            if swap is None:
                continue
            new_cards, old_cards = swap
            _apply_hero_hand_swap(base_hand, new_cards, old_cards)
            _apply_hero_hand_swap(treat_hand, new_cards, old_cards)

        split = False
        guard = 0
        while not base_hand.finished and not treat_hand.finished and guard < 500:
            base_seat = base_hand.current_actor()
            treat_seat = treat_hand.current_actor()
            if base_seat != treat_seat or base_seat is None:
                break

            base_before = copy.deepcopy(base_hand)
            treat_before = copy.deepcopy(treat_hand)
            base_action = _choose_and_apply(base_hand, base_seat, hand_index, guard, base_turnover, baseline_state, base_seed, force_opponent_reraise)
            treat_action = _choose_and_apply(treat_hand, treat_seat, hand_index, guard, treat_turnover, treatment_state, base_seed, force_opponent_reraise)

            same_action = base_action[0] == treat_action[0] and (base_action[1] == treat_action[1])
            if not same_action and base_seat == HERO_SEAT:
                split = True
                divergent += 1

                random_base = copy.deepcopy(base_hand)
                random_treat = copy.deepcopy(treat_hand)
                rb = _continue_to_finish(random_base, hand_index, base_turnover, baseline_state, branch_id=0, base_seed=base_seed)
                rt = _continue_to_finish(random_treat, hand_index, treat_turnover, treatment_state, branch_id=0, base_seed=base_seed)
                if rb is not None and rt is not None:
                    random_deltas.append(rt - rb)

                cards = _available_next_cards(base_hand, treat_hand)
                branch_counts.append(len(cards))
                branch_deltas: list[float] = []
                for branch_id, card_str in enumerate(cards, start=1):
                    b = copy.deepcopy(base_hand)
                    t = copy.deepcopy(treat_hand)
                    _force_next_board_card(b, card_str)
                    _force_next_board_card(t, card_str)
                    nb = _continue_to_finish(b, hand_index, base_turnover, baseline_state, branch_id=branch_id, base_seed=base_seed)
                    nt = _continue_to_finish(t, hand_index, treat_turnover, treatment_state, branch_id=branch_id, base_seed=base_seed)
                    if nb is not None and nt is not None:
                        branch_deltas.append(nt - nb)
                if branch_deltas:
                    enum_deltas.append(sum(branch_deltas) / len(branch_deltas))
                elif rb is not None and rt is not None:
                    enum_deltas.append(rt - rb)
                break

            # If a non-hero action somehow differs, restore and just continue
            # both worlds independently; this probe is about hero-rule splits.
            if not same_action:
                base_hand = base_before
                treat_hand = treat_before
                break
            guard += 1

        if not split:
            random_deltas.append(0.0)
            enum_deltas.append(0.0)

        # 2026-08-21 (tilt sequence infra): update each turnover's live
        # tilt-window state from the hand that actually just played out --
        # but ONLY when that hand genuinely finished. A divergent hand
        # (split=True) breaks out before base_hand/treat_hand reach
        # Hand.finished (the delta computation forks separate COPIES via
        # _continue_to_finish instead) -- the .finished guard below
        # naturally skips updating tilt state from those forks, avoiding
        # the ambiguity of which hypothetical outcome (random continuation
        # vs one of N enumerated branches) should count as "the" result
        # for a shared, persistent turnover object. This means opponent
        # tilt accumulation is driven only by hands where hero's rule-
        # under-test made no difference -- typically 95%+ of hands, so
        # real incidence is barely affected by skipping the rest.
        if base_hand.finished:
            base_turnover.record_hand_for_tilt(base_hand)
        if treat_hand.finished:
            treat_turnover.record_hand_for_tilt(treat_hand)
    return divergent


def _parse_archetypes(value: str | None) -> list[str] | None:
    if not value:
        return None
    archetypes = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(archetypes) - set(ARCHETYPE_POOL))
    if unknown:
        raise ValueError(f"unknown archetypes: {', '.join(unknown)}; options: {', '.join(ARCHETYPE_POOL)}")
    return archetypes or None


def _new_probe_state(
    allowed_archetypes: list[str] | None, base_seed: int = 42
) -> tuple[Table, Table, TableTurnover, TableTurnover]:
    bot_seats = [s for s in range(1, MAX_SEATS + 1) if s != HERO_SEAT]
    return (
        _make_table(),
        _make_table(),
        TableTurnover(bot_seats, rng_seed=base_seed, allowed_archetypes=allowed_archetypes),
        TableTurnover(bot_seats, rng_seed=base_seed, allowed_archetypes=allowed_archetypes),
    )


def _print_probe_summary(
    label: str,
    preset: str,
    n_hands: int,
    divergent: int,
    branch_counts: list[int],
    random_deltas: list[float],
    enum_deltas: list[float],
    elapsed: float,
) -> None:
    random_delta, random_ci = _stats(random_deltas)
    enum_delta, enum_ci = _stats(enum_deltas)
    shrink = random_ci / enum_ci if enum_ci else float("inf")
    avg_branches = statistics.mean(branch_counts) if branch_counts else 0.0
    print(f"{label} ({preset})")
    print(f"hands: {n_hands}, divergent hero hands: {divergent} ({divergent / n_hands * 100:.2f}%)")
    print(f"avg next-card branches when divergent: {avg_branches:.1f}")
    print(f"random continuation delta: {random_delta:+.2f} bb/100 (95% CI +/- {random_ci:.2f})")
    print(f"next-card enumerated delta: {enum_delta:+.2f} bb/100 (95% CI +/- {enum_ci:.2f})")
    print(f"CI shrink from enumeration: {shrink:.2f}x")
    print(f"elapsed: {elapsed:.2f}s")


def _original_state_for(comparison: ProbeComparison) -> dict[str, object]:
    names = set(comparison.baseline) | set(comparison.treatment) | {"MULTIWAY_AWARE"}
    return {name: getattr(abc_bot, name) for name in names if hasattr(abc_bot, name)}


def _resolve_hero_hand_filter(
    comparison: ProbeComparison, hero_hand_filter: set[str] | None
) -> set[str] | None:
    """Explicit --hero-hand-filter always wins. Otherwise, auto-infer from
    the preset's own FOLDABLE_PREMIUM_VS_EXTREME_AGGRO value when present
    (v26/r15v-* presets) -- these rules only ever fire with a specific,
    narrow hero-hand set (e.g. QQ+/AK is ~1.8% of hands), so without this,
    an adaptive run would burn its whole max_zero_divergent_hands budget on
    hands that could never trigger the rule at all."""
    if hero_hand_filter is not None:
        return hero_hand_filter
    inferred = comparison.treatment.get("FOLDABLE_PREMIUM_VS_EXTREME_AGGRO") or comparison.baseline.get(
        "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO"
    )
    return set(inferred) if inferred else None


def run_probe(
    preset: str,
    n_hands: int,
    comparison_mode: Literal["current", "historical", "ablation"],
    allowed_archetypes: list[str] | None,
    hero_hand_filter: set[str] | None = None,
    base_seed: int = 42,
    force_opponent_reraise: bool = False,
) -> None:
    _, label = _all_test_groups()[preset]
    comparison = _build_comparison(preset, comparison_mode)
    original = _original_state_for(comparison)
    base_table, treat_table, base_turnover, treat_turnover = _new_probe_state(allowed_archetypes, base_seed)
    hero_hand_filter = _resolve_hero_hand_filter(comparison, hero_hand_filter)

    random_deltas: list[float] = []
    enum_deltas: list[float] = []
    divergent = 0
    branch_counts: list[int] = []
    t0 = time.perf_counter()
    try:
        divergent += _run_probe_chunk(
            comparison.baseline,
            comparison.treatment,
            base_table,
            treat_table,
            base_turnover,
            treat_turnover,
            0,
            n_hands,
            random_deltas,
            enum_deltas,
            branch_counts,
            hero_hand_filter,
            base_seed,
            force_opponent_reraise,
        )
    finally:
        _restore_flags(original)

    archetype_label = ",".join(allowed_archetypes) if allowed_archetypes else "population"
    hero_hand_label = ",".join(sorted(hero_hand_filter)) if hero_hand_filter else "any (natural incidence)"
    print(f"comparison: {comparison.label}; archetypes={archetype_label}; hero_hand_filter={hero_hand_label}; base_seed={base_seed}", flush=True)
    _print_probe_summary(label, preset, n_hands, divergent, branch_counts, random_deltas, enum_deltas, time.perf_counter() - t0)


def _adaptive_stop_reason(
    n_hands: int,
    divergent: int,
    enum_delta: float,
    enum_ci: float,
    *,
    min_hands: int,
    max_hands: int,
    max_zero_divergent_hands: int,
    min_divergent: int,
    max_divergent: int,
    target_ci: float,
    effect_ratio: float,
) -> str | None:
    if n_hands >= max_hands:
        return "max_hands"
    if divergent >= max_divergent:
        return "max_divergent"
    if divergent == 0 and max_zero_divergent_hands > 0 and n_hands >= max_zero_divergent_hands:
        return "no_divergent_hands"
    if n_hands < min_hands or divergent < min_divergent:
        return None
    abs_delta = abs(enum_delta)
    if enum_delta < 0 and enum_ci <= abs_delta:
        return "confirmed_negative"
    if enum_delta > 0 and enum_ci <= abs_delta * effect_ratio:
        return "confirmed_positive"
    if enum_ci <= target_ci and enum_ci <= abs_delta * effect_ratio:
        return "confirmed_precise"
    if enum_ci <= target_ci and abs(enum_delta) < target_ci:
        return "inconclusive_small_effect"
    return None


def run_adaptive_probe(
    preset: str,
    *,
    comparison_mode: Literal["current", "historical", "ablation"],
    target_ci: float,
    effect_ratio: float,
    min_hands: int,
    max_hands: int,
    max_zero_divergent_hands: int,
    chunk_size: int,
    min_divergent: int,
    max_divergent: int,
    allowed_archetypes: list[str] | None,
    hero_hand_filter: set[str] | None = None,
    base_seed: int = 42,
    force_opponent_reraise: bool = False,
) -> None:
    _, label = _all_test_groups()[preset]
    comparison = _build_comparison(preset, comparison_mode)
    original = _original_state_for(comparison)
    base_table, treat_table, base_turnover, treat_turnover = _new_probe_state(allowed_archetypes, base_seed)
    hero_hand_filter = _resolve_hero_hand_filter(comparison, hero_hand_filter)
    random_deltas: list[float] = []
    enum_deltas: list[float] = []
    branch_counts: list[int] = []
    divergent = 0
    n_hands = 0
    t0 = time.perf_counter()
    stop_reason = None
    archetype_label = ",".join(allowed_archetypes) if allowed_archetypes else "population"
    hero_hand_label = ",".join(sorted(hero_hand_filter)) if hero_hand_filter else "any (natural incidence)"
    print(
        f"adaptive chance-enumeration: {label} ({preset}), "
        f"comparison={comparison.label}, "
        f"archetypes={archetype_label}, "
        f"hero_hand_filter={hero_hand_label}, base_seed={base_seed}, "
        f"force_opponent_reraise={force_opponent_reraise}, "
        f"target_ci={target_ci}, effect_ratio={effect_ratio}, min/max hands={min_hands}/{max_hands}, "
        f"max_zero_divergent_hands={max_zero_divergent_hands}, "
        f"min/max divergent={min_divergent}/{max_divergent}, chunk={chunk_size}",
        flush=True,
    )
    try:
        while n_hands < max_hands:
            this_chunk = min(chunk_size, max_hands - n_hands)
            divergent += _run_probe_chunk(
                comparison.baseline,
                comparison.treatment,
                base_table,
                treat_table,
                base_turnover,
                treat_turnover,
                n_hands,
                this_chunk,
                random_deltas,
                enum_deltas,
                branch_counts,
                hero_hand_filter,
                base_seed,
                force_opponent_reraise,
            )
            n_hands += this_chunk
            random_delta, random_ci = _stats(random_deltas)
            enum_delta, enum_ci = _stats(enum_deltas)
            elapsed = time.perf_counter() - t0
            print(
                f"progress hands={n_hands} divergent={divergent} ({divergent / n_hands * 100:.2f}%) "
                f"random_delta={random_delta:+.2f} random_ci={random_ci:.2f} "
                f"enum_delta={enum_delta:+.2f} enum_ci={enum_ci:.2f} elapsed={elapsed:.1f}s",
                flush=True,
            )
            stop_reason = _adaptive_stop_reason(
                n_hands,
                divergent,
                enum_delta,
                enum_ci,
                min_hands=min_hands,
                max_hands=max_hands,
                max_zero_divergent_hands=max_zero_divergent_hands,
                min_divergent=min_divergent,
                max_divergent=max_divergent,
                target_ci=target_ci,
                effect_ratio=effect_ratio,
            )
            if stop_reason:
                break
    finally:
        _restore_flags(original)

    print(f"stop_reason: {stop_reason or 'finished'}", flush=True)
    _print_probe_summary(label, preset, n_hands, divergent, branch_counts, random_deltas, enum_deltas, time.perf_counter() - t0)


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("preset", nargs="?", default="v16-iso-limpers")
    parser.add_argument("n_hands", nargs="?", type=int, default=1000)
    parser.add_argument(
        "--comparison",
        choices=("current", "historical", "ablation"),
        default="current",
        help=(
            "current overlays only the tested flags on today's defaults; "
            "historical resets known A/B flags to the preset's at-introduction context; "
            "ablation compares today's full model against full model with the tested flags disabled"
        ),
    )
    parser.add_argument("--adaptive", action="store_true", help="run chunks until effect-strength/precision or hard-cap stop criteria are met")
    parser.add_argument("--archetypes", help="comma-separated opponent archetypes to seat; omitted means the real population mix")
    parser.add_argument(
        "--hero-hand-filter",
        help=(
            "comma-separated hand notations (e.g. QQ,AKs,AKo) to force hero's dealt "
            "hand to, instead of natural incidence -- auto-inferred for presets whose "
            "rule only fires on a specific hero-hand set (e.g. v26/r15v-fold-* read "
            "FOLDABLE_PREMIUM_VS_EXTREME_AGGRO); pass 'none' to disable auto-inference "
            "and use natural incidence anyway"
        ),
    )
    parser.add_argument("--target-ci", type=float, default=1.0)
    parser.add_argument("--effect-ratio", type=float, default=0.5, help="positive effect is confirmed when CI <= abs(delta) * this ratio")
    parser.add_argument("--min-hands", type=int, default=5_000)
    parser.add_argument("--max-hands", type=int, default=500_000)
    parser.add_argument("--max-zero-divergent-hands", type=int, default=50_000)
    parser.add_argument("--chunk-size", type=int, default=2_000)
    parser.add_argument("--min-divergent", type=int, default=30)
    parser.add_argument("--max-divergent", type=int, default=2_000)
    parser.add_argument(
        "--base-seed",
        type=int,
        default=42,
        help=(
            "base seed for deck deal / ML-bot decisions / turnover / hero-hand-filter draws "
            "(everything derives from _common_seed(base_seed, ...)) -- every run in this file "
            "defaulted to 42 until now; pass a different value for a genuinely independent "
            "second sample, e.g. to cross-check a confirmed_positive/negative result the way "
            "this project's own standard requires before calling something permanently confirmed"
        ),
    )
    parser.add_argument(
        "--force-opponent-reraise",
        action="store_true",
        help=(
            "force the opponent facing hero's own preflop raise to re-raise (min-legal size) "
            "instead of using their trained model -- for rules gated on hero FACING a re-raise "
            "(r13/v26/r15v-fold-*/r18v-shove-*), which this population's real 3-bet/4-bet "
            "frequency is too low to naturally surface even across hundreds of thousands of "
            "hands (confirmed via r13: 0 divergent over 50k even with hero's cards forced to "
            "AA/KK). Applied identically to both baseline and treatment for a valid paired "
            "comparison, same principle as --hero-hand-filter. Opponent's cards are ALSO forced "
            "(to VALUE_3BET_WIDE, a real premium 3-betting range -- OPPONENT_RERAISE_HAND_SET), "
            "not just their action. READ THIS BEFORE TRUSTING A NUMBER: combined with "
            "--hero-hand-filter, this pushes a spot real self-play reaches on well under 0.1% of "
            "hands up to 60%+ of the SAMPLE -- smoke tests measured deltas in the THOUSANDS of "
            "bb/100 (2026-08-12/13), which looked like a bug at first but isn't one: enum_delta "
            "is the mean per-hand delta over ALL sampled hands (0.0 for every non-divergent one, "
            "see _run_probe_chunk), so forcing a decision to occur ~1000x more often than reality "
            "inflates its reported bb/100 contribution by roughly that same factor. The raw number "
            "this flag produces is NOT a population bb/100 -- rescale it by (true incidence of the "
            "targeted spot) / (this sample's forced incidence, printed as the divergent-hand "
            "percentage) to get a real contribution estimate. True incidence isn't measured "
            "precisely yet; until it is, treat this flag as confirming a rule's branch is reachable "
            "and correctly ordered in EV sign, not as a literal magnitude."
        ),
    )
    args = parser.parse_args()
    preset = args.preset
    groups = _all_test_groups()
    if preset not in groups:
        raise SystemExit(f"unknown preset {preset}; options: {', '.join(groups)}")
    try:
        allowed_archetypes = _parse_archetypes(args.archetypes)
        if args.hero_hand_filter is None:
            hero_hand_filter = None  # auto-infer from the preset, if applicable
        elif args.hero_hand_filter.strip().lower() == "none":
            hero_hand_filter = set()  # explicit opt-out -- _resolve treats non-None as final, but an empty set is falsy everywhere it's checked
        else:
            hero_hand_filter = {n.strip() for n in args.hero_hand_filter.split(",") if n.strip()}
        if args.adaptive:
            run_adaptive_probe(
                preset,
                comparison_mode=args.comparison,
                target_ci=args.target_ci,
                effect_ratio=args.effect_ratio,
                min_hands=args.min_hands,
                max_hands=args.max_hands,
                max_zero_divergent_hands=args.max_zero_divergent_hands,
                chunk_size=args.chunk_size,
                min_divergent=args.min_divergent,
                max_divergent=args.max_divergent,
                allowed_archetypes=allowed_archetypes,
                hero_hand_filter=hero_hand_filter,
                base_seed=args.base_seed,
                force_opponent_reraise=args.force_opponent_reraise,
            )
        else:
            run_probe(
                preset, args.n_hands, args.comparison, allowed_archetypes,
                hero_hand_filter, args.base_seed, args.force_opponent_reraise,
            )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
