"""Per-flag drill specs: what forcing lever(s) (see forcing.py) need to be
active so a given abc_bot.py rule's trigger scenario comes up reliably in a
live Telegram session, instead of at its natural (sometimes <0.1%) self-play
incidence. Covers all 32 currently-True flags in abc_bot.py -- classified
this session by reading each flag's own gating condition directly in the
source, not guessed.

Board-texture-gated rules (SIZE_UP_ON_WET_BOARD, NUT_ADVANTAGE_SIZING) have
no forcing lever here -- no "pick a wet/dry board" selection logic exists
anywhere in this codebase yet (deliberately deferred, see the plan this was
built from); their DrillSpec is empty (population/context still narrows via
whatever other levers apply, the board itself stays natural).
"""

from dataclasses import dataclass, field

from backend.bots import abc_bot

# Real population archetype sets a rule reads, pulled directly from
# abc_bot.py's own constants -- not redefined/guessed here.
TIGHT_ARCHETYPES = {"Nit", "TAG", "LAG"}
LOOSE_ARCHETYPES = {"Loose-passive", "Station", "Maniac"}
NIT_ONLY = {"Nit"}
MANIAC_STATION = {"Maniac", "Station"}


@dataclass(frozen=True)
class DrillSpec:
    archetype_filter: frozenset[str] = frozenset()
    freq_tier_seats: dict[str, int] = field(default_factory=dict)
    force_tilt: bool = False
    hero_hand_notations: frozenset[str] = frozenset()
    hero_position: str | None = None
    force_opponent_open: bool = False
    force_opponent_reraise: bool = False
    force_opponent_limp: bool = False


# Category labels for the /drills menu -- one of preflop-range/
# preflop-sizing/postflop-calling/postflop-bluffing/postflop-sizing.
FLAG_CATEGORY: dict[str, str] = {
    "SET_MINE_IMPLIED_ODDS": "preflop-range",
    "STEAL_WIDER_VS_NIT": "preflop-range",
    "SB_THREEBET_OR_FOLD_VS_STEAL": "preflop-range",
    "THREEBET_SIZE_BY_POSITION": "preflop-sizing",
    "TIGHT_BIG_ISO_RAISE_LIMPERS": "preflop-range",
    "TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR": "preflop-range",
    "LIMP_BEHIND_OVER_LIMPERS": "preflop-range",
    "SIZE_UP_PREMIUM_OPENS": "preflop-sizing",
    "USE_WIDE_VALUE_3BET": "preflop-range",
    "SHOVE_AA_KK_VS_3BET_PLUS": "preflop-range",
    "WIDER_3BET_VS_LOOSE": "preflop-range",
    "ALLOW_CALLING_RAISES": "preflop-range",
    "BLUFF_3BET_VS_TIGHT": "preflop-range",
    "THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT": "preflop-range",
    "BB_DEFEND_VS_STEAL_MINRAISE": "preflop-range",
    "BB_DEFEND_MDF_SCALED": "preflop-range",
    "RIVER_OVERBET_NUTS_VS_LOOSE": "postflop-sizing",
    "TURN_OVERBET_NUTS_VS_LOOSE": "postflop-sizing",
    "OPTIMAL_VALUE_SIZING_PER_ARCHETYPE": "postflop-sizing",
    "SIZE_UP_WITH_VERY_STRONG_HAND": "postflop-sizing",
    "SIZE_UP_ON_WET_BOARD": "postflop-sizing",
    "DONK_BLUFF_VS_TIGHT": "postflop-bluffing",
    "BLUFF_VS_RARE_TIER": "postflop-bluffing",
    "BARREL_BLUFF_VS_TIGHT": "postflop-bluffing",
    "UNCONDITIONAL_FLOP_CBET": "postflop-bluffing",
    "WIDER_CALL_VS_OFTEN_TIER": "postflop-calling",
    "WIDER_CALL_VS_TILTING_OPPONENT": "postflop-calling",
    "NUT_ADVANTAGE_SIZING": "postflop-sizing",
    "SPR_SCALED_THRESHOLDS": "postflop-calling",
    "FLOAT_FLOP_IN_POSITION": "postflop-bluffing",
    "FLOAT_TURN_IN_POSITION": "postflop-bluffing",
    "RIVER_BLUFF_MISSED_DRAW": "postflop-bluffing",
}

CATEGORY_LABEL_RU = {
    "preflop-range": "Диапазоны префлоп",
    "preflop-sizing": "Сайзинг префлоп",
    "postflop-calling": "Колл постфлоп",
    "postflop-bluffing": "Блеф постфлоп",
    "postflop-sizing": "Сайзинг постфлоп",
}

PREFLOP_FLAGS = [f for f, c in FLAG_CATEGORY.items() if c.startswith("preflop")]
POSTFLOP_FLAGS = [f for f, c in FLAG_CATEGORY.items() if c.startswith("postflop")]

# Short Russian labels for the /drills menu buttons -- one line each, not a
# full description (the flag's own comment in abc_bot.py has that).
FLAG_LABEL_RU: dict[str, str] = {
    "SET_MINE_IMPLIED_ODDS": "Сет-майнинг (имплайд-одды)",
    "STEAL_WIDER_VS_NIT": "Стил шире против нита",
    "SB_THREEBET_OR_FOLD_VS_STEAL": "SB: 3-бет или фолд против стила",
    "THREEBET_SIZE_BY_POSITION": "Сайзинг 3-бета по позиции",
    "TIGHT_BIG_ISO_RAISE_LIMPERS": "Изо большим рейзом против лимперов",
    "TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR": "Изо-диапазон + реальные данные",
    "LIMP_BEHIND_OVER_LIMPERS": "Лимп за лимперами",
    "SIZE_UP_PREMIUM_OPENS": "Больше сайзинг с премиум-рукой",
    "USE_WIDE_VALUE_3BET": "Широкий вэлью-3-бет",
    "SHOVE_AA_KK_VS_3BET_PLUS": "Шовим AA/KK+ против 3-бета+",
    "WIDER_3BET_VS_LOOSE": "Шире 3-бет против лузового рейзера",
    "ALLOW_CALLING_RAISES": "Колл рейза (не только 3-бет/фолд)",
    "BLUFF_3BET_VS_TIGHT": "Блеф-3-бет против тайтового",
    "THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT": "Блеф-3-бет из поздней позиции",
    "BB_DEFEND_VS_STEAL_MINRAISE": "BB защита против минрейз-стила",
    "BB_DEFEND_MDF_SCALED": "BB защита по MDF",
    "RIVER_OVERBET_NUTS_VS_LOOSE": "Овербет ривер нутсами (лузовый)",
    "TURN_OVERBET_NUTS_VS_LOOSE": "Овербет тёрн нутсами (лузовый)",
    "OPTIMAL_VALUE_SIZING_PER_ARCHETYPE": "Вэлью-сайзинг по архетипу",
    "SIZE_UP_WITH_VERY_STRONG_HAND": "Больше сайзинг с очень сильной рукой",
    "SIZE_UP_ON_WET_BOARD": "Больше сайзинг на мокром борде",
    "DONK_BLUFF_VS_TIGHT": "Донк-блеф против тайтового",
    "BLUFF_VS_RARE_TIER": "Блеф против редко играющего",
    "BARREL_BLUFF_VS_TIGHT": "Продолжение блефа (баррель)",
    "UNCONDITIONAL_FLOP_CBET": "Безусловный к-бет флопа",
    "WIDER_CALL_VS_OFTEN_TIER": "Шире колл против часто играющего",
    "WIDER_CALL_VS_TILTING_OPPONENT": "Шире колл против тильтующего",
    "NUT_ADVANTAGE_SIZING": "Сайзинг при нат-адвантидже",
    "SPR_SCALED_THRESHOLDS": "Порог колла по SPR",
    "FLOAT_FLOP_IN_POSITION": "Флоат флопа в позиции",
    "FLOAT_TURN_IN_POSITION": "Флоат тёрна в позиции",
    "RIVER_BLUFF_MISSED_DRAW": "Блеф ривера с непопавшим дро",
}

DRILL_SPECS: dict[str, DrillSpec] = {
    # --- preflop-range ---
    "SET_MINE_IMPLIED_ODDS": DrillSpec(
        hero_hand_notations=frozenset(abc_bot.SET_MINE_POCKET_PAIRS | abc_bot.SET_MINE_SUITED_CONNECTORS),
        force_opponent_open=True,
    ),
    "STEAL_WIDER_VS_NIT": DrillSpec(archetype_filter=frozenset(NIT_ONLY)),
    "SB_THREEBET_OR_FOLD_VS_STEAL": DrillSpec(hero_position="SB", force_opponent_open=True),
    "TIGHT_BIG_ISO_RAISE_LIMPERS": DrillSpec(force_opponent_limp=True),
    "TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR": DrillSpec(force_opponent_limp=True),
    "LIMP_BEHIND_OVER_LIMPERS": DrillSpec(force_opponent_limp=True),
    "SIZE_UP_PREMIUM_OPENS": DrillSpec(hero_hand_notations=frozenset(abc_bot.VALUE_3BET_TIGHT)),
    "USE_WIDE_VALUE_3BET": DrillSpec(force_opponent_open=True),
    "SHOVE_AA_KK_VS_3BET_PLUS": DrillSpec(
        hero_hand_notations=frozenset(abc_bot.SHOVE_VS_3BET_PLUS_RANGE), force_opponent_reraise=True
    ),
    "WIDER_3BET_VS_LOOSE": DrillSpec(archetype_filter=frozenset(MANIAC_STATION), force_opponent_open=True),
    "ALLOW_CALLING_RAISES": DrillSpec(force_opponent_open=True),
    "BLUFF_3BET_VS_TIGHT": DrillSpec(
        archetype_filter=frozenset(TIGHT_ARCHETYPES),
        hero_hand_notations=frozenset(abc_bot.BLUFF_3BET_RANGE),
        force_opponent_open=True,
    ),
    "THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT": DrillSpec(
        hero_position="CO", hero_hand_notations=frozenset(abc_bot.BLUFF_3BET_RANGE), force_opponent_open=True
    ),
    "BB_DEFEND_VS_STEAL_MINRAISE": DrillSpec(hero_position="BB", force_opponent_open=True),
    "BB_DEFEND_MDF_SCALED": DrillSpec(hero_position="BB", force_opponent_open=True),
    # --- preflop-sizing (no natural-scenario gate to force -- these apply
    # on most opens/3-bets already, "drilling" them just means playing a
    # normal session and paying attention) ---
    "THREEBET_SIZE_BY_POSITION": DrillSpec(force_opponent_open=True),
    # --- postflop-sizing ---
    "RIVER_OVERBET_NUTS_VS_LOOSE": DrillSpec(archetype_filter=frozenset(LOOSE_ARCHETYPES)),
    "TURN_OVERBET_NUTS_VS_LOOSE": DrillSpec(archetype_filter=frozenset(LOOSE_ARCHETYPES)),
    "OPTIMAL_VALUE_SIZING_PER_ARCHETYPE": DrillSpec(),
    "SIZE_UP_WITH_VERY_STRONG_HAND": DrillSpec(),
    "SIZE_UP_ON_WET_BOARD": DrillSpec(),
    "NUT_ADVANTAGE_SIZING": DrillSpec(),
    # --- postflop-bluffing ---
    "DONK_BLUFF_VS_TIGHT": DrillSpec(archetype_filter=frozenset(TIGHT_ARCHETYPES)),
    "BLUFF_VS_RARE_TIER": DrillSpec(freq_tier_seats={"rare": 6}),
    "BARREL_BLUFF_VS_TIGHT": DrillSpec(archetype_filter=frozenset(TIGHT_ARCHETYPES)),
    "UNCONDITIONAL_FLOP_CBET": DrillSpec(),
    "FLOAT_FLOP_IN_POSITION": DrillSpec(archetype_filter=frozenset(TIGHT_ARCHETYPES)),
    "FLOAT_TURN_IN_POSITION": DrillSpec(archetype_filter=frozenset(TIGHT_ARCHETYPES)),
    "RIVER_BLUFF_MISSED_DRAW": DrillSpec(archetype_filter=frozenset(TIGHT_ARCHETYPES)),
    # --- postflop-calling ---
    "WIDER_CALL_VS_OFTEN_TIER": DrillSpec(freq_tier_seats={"often": 6}),
    "WIDER_CALL_VS_TILTING_OPPONENT": DrillSpec(force_tilt=True),
    "SPR_SCALED_THRESHOLDS": DrillSpec(),
}


def merge_specs(flag_names: list[str]) -> DrillSpec:
    """Combines 2+ selected flags' DrillSpecs: archetype filters union
    (never intersect -- an empty intersection would make a multi-select
    drill silently impossible), freq_tier requests each get their own
    opponent seat where possible, hero-hand notations union, and
    conflicting forced hero positions rotate hand-by-hand rather than
    picking one arbitrarily (callers pick the active position for "this"
    hand via `resolve_position(merged, hand_number)`)."""
    archetype_filter: set[str] = set()
    freq_tier_seats: dict[str, int] = {}
    force_tilt = False
    hero_hand_notations: set[str] = set()
    positions: list[str] = []
    force_opponent_open = False
    force_opponent_reraise = False
    force_opponent_limp = False

    for name in flag_names:
        spec = DRILL_SPECS.get(name)
        if spec is None:
            continue
        archetype_filter |= set(spec.archetype_filter)
        for tier, count in spec.freq_tier_seats.items():
            freq_tier_seats[tier] = max(freq_tier_seats.get(tier, 0), count)
        force_tilt = force_tilt or spec.force_tilt
        hero_hand_notations |= set(spec.hero_hand_notations)
        if spec.hero_position and spec.hero_position not in positions:
            positions.append(spec.hero_position)
        force_opponent_open = force_opponent_open or spec.force_opponent_open
        force_opponent_reraise = force_opponent_reraise or spec.force_opponent_reraise
        force_opponent_limp = force_opponent_limp or spec.force_opponent_limp

    return DrillSpec(
        archetype_filter=frozenset(archetype_filter),
        freq_tier_seats=freq_tier_seats,
        force_tilt=force_tilt,
        hero_hand_notations=frozenset(hero_hand_notations),
        hero_position=tuple(positions) if positions else None,  # type: ignore[assignment]
        force_opponent_open=force_opponent_open,
        force_opponent_reraise=force_opponent_reraise,
        force_opponent_limp=force_opponent_limp,
    )


def resolve_position(merged: DrillSpec, hand_number: int) -> str | None:
    """merge_specs stashes ALL requested positions in hero_position when
    there's more than one (as a tuple, a deliberate abuse of the field so
    merge_specs itself stays a pure combiner) -- this picks which one is
    active for a given hand, rotating through them one per hand so a
    multi-position multi-select drill still covers every position over a
    few hands instead of only ever hitting the first one picked."""
    pos = merged.hero_position
    if pos is None:
        return None
    if isinstance(pos, tuple):
        return pos[hand_number % len(pos)]
    return pos


def freq_tier_assignment(merged: DrillSpec, opponent_seats: list[int]) -> dict[int, str]:
    """Assigns each requested freq_tier to its own opponent seat(s), up to
    however many live opponent seats exist -- e.g. selecting both
    BLUFF_VS_RARE_TIER and WIDER_CALL_VS_OFTEN_TIER seats one "rare" and
    one "often" opponent rather than forcing the whole table to one tier."""
    assignment: dict[int, str] = {}
    seats = list(opponent_seats)
    for tier, count in merged.freq_tier_seats.items():
        for _ in range(min(count, len(seats))):
            if not seats:
                break
            assignment[seats.pop(0)] = tier
    return assignment
