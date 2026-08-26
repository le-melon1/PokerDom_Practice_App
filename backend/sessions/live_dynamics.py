"""Wires Phase B's real session-length-by-archetype distributions into live
gameplay: each bot is given a planned session length sampled from its
archetype's actual empirical distribution (bootstrap resampling from real
per-table session records, not a guessed/uniform duration). When a bot's
hand count reaches that sample (or it busts, whichever comes first), it
leaves and a freshly seated bot (new archetype, new planned length, new
dossier) takes the seat -- so the table's population turns over the way a
real one does, not just "everyone sits until they bust."
"""

import random
from pathlib import Path

import pandas as pd

RAW_SESSIONS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "session_lengths_raw.csv"
ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
ARCHETYPE_POOL = ["Nit", "TAG", "LAG", "Loose-passive", "Station", "Maniac"]

# Real population mix, not a guess: counts of uniquely labeled players (>=100
# hands, same MIN_HANDS_FOR_LABEL gate as the analysis project) via
# pipeline.archetypes.label_archetypes, renormalized over the 6 known
# archetypes (excluding "Insufficient sample"). Confirms the expected
# microlimit shape: Loose-passive/Station dominate, Maniac/Nit are rare --
# even more so after the 2026-07-30 dataset expansion (1000 -> 4379
# PokerStars files, 3.56M hands, 26,797 labeled players vs 8,619 before):
# Loose-passive+Station+Maniac combined went from 57.9% to 68.5% of the
# population.
#
# 2026-08-19: refreshed again after archetypes.py's Maniac definition
# changed from postflop-af-gated (vpip>0.45 and af>=2.0) to purely
# preflop (vpip>0.45 and pfr_ratio>=0.45) -- see that module's own
# docstring for why. Real, large shift: Maniac drops from 3352 to 756
# (12.5% -> 2.8% of the population) now that postflop aggression is its
# own independent axis (POSTFLOP_FREQ_TIER) instead of partly defining
# the preflop archetype. Station and Loose-passive absorbed most of the
# reclassified players.
#   Loose-passive=8602  Station=9184  LAG=3717  Maniac=756  TAG=2547  Nit=1991
ARCHETYPE_POPULATION_WEIGHTS = {
    "Loose-passive": 8602,
    "Station": 9184,
    "LAG": 3717,
    "Maniac": 756,
    "TAG": 2547,
    "Nit": 1991,
}

# 2026-08-20: second independent axis -- postflop raise-frequency tier
# (rare/normal/often), split out of the archetype label itself so it can be
# read separately from the (now purely preflop) archetype. Infra-only so
# far, per user's explicit choice: this seats bots with a real tier and
# makes it readable, but no decision in abc_bot.py reads it yet, and the
# ML opponent model was NOT retrained with it as a feature -- so seated
# bots' actual behavior does not yet vary by their assigned tier. Building
# that (adding the feature + retrain) is deliberately deferred to a
# separate step once real strategies are ready to consume the signal.
#
# Thresholds match src/pipeline/archetypes.py in PokerDom_Microlimits_
# Analysis exactly (AF<2.0 rare / 2.0-3.0 normal / >3.0 often,
# literature-grounded, not fit to this dataset) -- keep both in sync if
# either changes.
FREQ_TIER_POOL = ["rare", "normal", "often"]
POSTFLOP_FREQ_RARE_MAX = 2.0
POSTFLOP_FREQ_OFTEN_MIN = 3.0


def _freq_tier_from_af(af: float) -> str:
    if af < POSTFLOP_FREQ_RARE_MAX:
        return "rare"
    if af > POSTFLOP_FREQ_OFTEN_MIN:
        return "often"
    return "normal"


# Real joint population counts: labeled players (label_archetypes' own
# postflop_freq_tier column) cross-tabulated by archetype, same 26,797-
# player dataset as ARCHETYPE_POPULATION_WEIGHTS above. Computed 2026-08-20
# directly from data/processed/actions.parquet in the analysis project --
# not a guess, not assumed independent of archetype (it isn't: e.g. Station
# skews "rare" 5370/9184=58% since passive-calling stations by definition
# raise less, while LAG is close to a 3-way split).
ARCHETYPE_FREQ_TIER_WEIGHTS = {
    "Nit": {"normal": 672, "often": 803, "rare": 516},
    "TAG": {"normal": 978, "often": 1084, "rare": 485},
    "LAG": {"normal": 1325, "often": 1186, "rare": 1206},
    "Loose-passive": {"normal": 2741, "often": 1838, "rare": 4023},
    "Station": {"normal": 2573, "often": 1241, "rare": 5370},
    "Maniac": {"normal": 315, "often": 259, "rare": 182},
}


# 2026-08-21: third session-scoped signal (unlike archetype/freq_tier,
# NOT a static per-seat label -- it changes hand-to-hand based on that
# seat's own recent results). Confirmed real on actual data
# (PokerDom_Microlimits_Analysis/scripts/check_tilt_after_cooler.py):
# losing a big pot (>=15bb invested, real showdown, lost) measurably
# loosens/tightens a player's next ~10 hands (VPIP +11.75pp, postflop
# aggression +5.76pp), decaying across the window. Same constants and
# tier buckets as that script and build_training_data.py's tilt_tier
# feature -- keep all three in sync if any changes.
COOLER_MIN_BB = 15.0
POST_COOLER_WINDOW = 10


def _tilt_tier_from_hands_since(hands_since_cooler: int | None) -> str:
    if hands_since_cooler is None:
        return "none"
    if hands_since_cooler <= 2:
        return "acute"
    if hands_since_cooler <= 5:
        return "fading"
    return "residual"


def sample_freq_tier(archetype: str, rng: random.Random | None = None) -> str:
    """Weighted-random tier conditioned on archetype, from the real joint
    distribution above."""
    rng = rng or random
    weights = ARCHETYPE_FREQ_TIER_WEIGHTS.get(archetype)
    if not weights:
        return rng.choice(FREQ_TIER_POOL)
    tiers = list(weights.keys())
    return rng.choices(tiers, weights=[weights[t] for t in tiers])[0]


# 2026-08-22: fourth session-scoped signal -- "how often does this
# player's shown aggression get caught bluffing at real showdown."
# Static per-seat label like archetype/freq_tier (not dynamic like
# tilt_tier), but with a real coverage problem the other three didn't
# have: only a minority of real players ever accumulate enough
# real-showdown-after-aggression events for a trustworthy individual
# estimate. Two competing definitions built and compared
# (scripts/compare_bluff_frequency_variants.py in the analysis project),
# per user's explicit "build both, compare" instruction rather than
# picking one on paper:
#   Variant A: last RIVER aggressor who reached a real showdown and lost
#     (find_frequent_bluffers.py's own original definition). Precise
#     concept ("led out on the river and got caught"), but only 777/
#     26,797 players (2.9%) clear a 15-showdown reliability bar.
#   Variant C: aggressor on ANY street that reached a real showdown and
#     lost (broader proxy -- "showed aggression this hand, didn't hold
#     up"). Less precise concept, but 7,974/26,797 players (29.8%) clear
#     the same 15-event bar -- an order of magnitude better coverage.
# Both use empirical-Bayes shrinkage (PRIOR_WEIGHT=30, same as
# find_frequent_bluffers.py) toward the population loss rate to control
# small-n noise, then a tercile split (low/normal/high) among reliable
# players. The large majority of simulated opponents will have no
# individual measurement either way -- "unknown" is sized to reflect
# that honestly (26,797 minus however many are reliable), not folded
# into "normal" as if it were a real read.
BLUFF_TIER_POOL = ["low", "normal", "high", "unknown"]
TOTAL_ARCHETYPE_POPULATION = 26_797  # same denominator as ARCHETYPE_POPULATION_WEIGHTS' total
BLUFF_TIER_A_WEIGHTS = {"low": 259, "normal": 251, "high": 267, "unknown": TOTAL_ARCHETYPE_POPULATION - 777}
BLUFF_TIER_C_WEIGHTS = {"low": 2657, "normal": 2645, "high": 2672, "unknown": TOTAL_ARCHETYPE_POPULATION - 7974}


def sample_bluff_tier(weights: dict[str, int], rng: random.Random | None = None) -> str:
    rng = rng or random
    tiers = list(weights.keys())
    return rng.choices(tiers, weights=[weights[t] for t in tiers])[0]


_bluff_tier_lookup_cache: dict[str, dict[str, str]] = {}


def _load_bluff_tier_lookup(variant: str) -> dict[str, str]:
    """{player: tier} for real players who cleared the 15-event reliability
    bar in that variant's CSV -- everyone else is absent (caller should
    default to "unknown"). Cached at module level, same pattern as
    player_profile_bots.py's load_profile_pool."""
    if variant not in _bluff_tier_lookup_cache:
        path = ANALYSIS_ROOT / "data" / "reference" / f"bluff_frequency_variant_{variant}.csv"
        df = pd.read_csv(path)
        df = df[df["n_events"] >= 15]
        q1, q2 = df["shrunk_rate"].quantile([1 / 3, 2 / 3])

        def _tier(rate: float) -> str:
            if rate < q1:
                return "low"
            if rate < q2:
                return "normal"
            return "high"

        _bluff_tier_lookup_cache[variant] = {row["player"]: _tier(row["shrunk_rate"]) for _, row in df.iterrows()}
    return _bluff_tier_lookup_cache[variant]


_lengths_by_archetype: dict[str, list[int]] | None = None


def _load_lengths() -> dict[str, list[int]]:
    global _lengths_by_archetype
    if _lengths_by_archetype is None:
        df = pd.read_csv(RAW_SESSIONS_PATH)
        _lengths_by_archetype = {
            arch: sub["session_length"].tolist() for arch, sub in df.groupby("archetype")
        }
    return _lengths_by_archetype


def sample_session_length(archetype: str, rng: random.Random | None = None) -> int:
    """Bootstrap: draw one real observed session length for this archetype."""
    rng = rng or random
    lengths = _load_lengths().get(archetype)
    if not lengths:
        return rng.randint(10, 40)  # fallback if an archetype has no recorded sessions
    return rng.choice(lengths)


class SeatOccupant:
    def __init__(
        self,
        archetype: str,
        planned_length: int,
        freq_tier: str,
        bluff_tier_a: str = "unknown",
        bluff_tier_c: str = "unknown",
        profile_id: str | None = None,
    ):
        self.archetype = archetype
        self.planned_length = planned_length
        self.freq_tier = freq_tier
        self.bluff_tier_a = bluff_tier_a
        self.bluff_tier_c = bluff_tier_c
        self.hands_played = 0
        # None in normal archetype mode. When set, this seat is a "real
        # player" bot (see backend/bots/player_profile_bots.py) instead of
        # the population-wide archetype model -- hands_played doubles as
        # that model's session_hands_so_far feature, the exact same causal
        # quantity build_player_profile_training_data.py computed it as.
        self.profile_id = profile_id
        # None = not currently in a post-cooler window. 1..COOLER_WINDOW =
        # hands since this seat's most recent qualifying cooler (see
        # TableTurnover.record_hand_for_tilt). Reset to None whenever a new
        # occupant is seated -- tilt is personal history, doesn't transfer.
        self.hands_since_cooler: int | None = None

    def should_leave(self, busted: bool) -> bool:
        return busted or self.hands_played >= self.planned_length


class TableTurnover:
    """Tracks each bot seat's current occupant and decides when to replace
    them, using real archetype-conditioned session lengths.

    `allowed_archetypes`: optional subset of ARCHETYPE_POOL to restrict who
    gets seated (e.g. "only practice against Nits") -- population weights
    among the allowed subset are preserved, not flattened to uniform, so
    restricting to a wide subset still feels like the real population mix.
    None/empty means the full pool, matching the original default.

    `player_profile_ids`: optional list of specific real-player profile_ids
    (backend/bots/player_profile_bots.py's ~20-player pool). When given and
    non-empty, this OVERRIDES allowed_archetypes entirely -- every bot seat
    is one of these specific real, individually-identified players (chosen
    uniformly, not weighted by their own hand count -- "play against these
    N people" should mean an equal chance of seeing each, not a chance
    proportional to how much historical data happened to exist for them)
    instead of the population-wide archetype model.

    `forced_freq_tier`: optional {seat: tier} override, for the Telegram
    bot's drill mode (2026-08-26) -- lets a specific seat be forced to a
    postflop_freq_tier regardless of what its archetype would normally
    sample, so a rule gated on freq_tier (e.g. WIDER_CALL_VS_OFTEN_TIER)
    can be drilled reliably. Applied only at seating time, same as a
    sampled tier would be -- does not persist across a reseat unless
    re-passed. Note: an archetype+tier combo the ML opponent model rarely
    saw in training (e.g. Nit+often, a real but skewed combo per
    ARCHETYPE_FREQ_TIER_WEIGHTS) makes that seat's behavior less
    calibrated in the forced region -- acceptable for a drill, not
    something to rely on for population-realistic EV."""

    def __init__(
        self,
        bot_seats: list[int],
        rng_seed: int | None = None,
        allowed_archetypes: list[str] | None = None,
        player_profile_ids: list[str] | None = None,
        forced_freq_tier: dict[int, str] | None = None,
    ):
        self.rng = random.Random(rng_seed)
        self.allowed_archetypes = [a for a in ARCHETYPE_POOL if a in allowed_archetypes] if allowed_archetypes else list(ARCHETYPE_POOL)
        if not self.allowed_archetypes:
            self.allowed_archetypes = list(ARCHETYPE_POOL)
        self.player_profile_ids = list(player_profile_ids) if player_profile_ids else None
        self.forced_freq_tier = dict(forced_freq_tier) if forced_freq_tier else {}
        self.occupants: dict[int, SeatOccupant] = {}
        for seat in bot_seats:
            self._seat_new_occupant(seat)

    def _seat_new_occupant(self, seat: int) -> SeatOccupant:
        if self.player_profile_ids:
            from backend.bots.player_profile_bots import load_profile_pool

            profile_id = self.rng.choice(self.player_profile_ids)
            profile = load_profile_pool()[profile_id]
            archetype = profile["archetype"]
            # Real players get their OWN measured tier (from their actual
            # aggression_factor), not a population sample -- more precise
            # than sampling since we already know this specific person's
            # postflop frequency.
            freq_tier = self.forced_freq_tier.get(seat, _freq_tier_from_af(profile["aggression_factor"]))
            # Real players get their OWN measured bluff tier too, when they
            # happen to clear the 15-event reliability bar in either
            # variant's table -- looked up by their real player id, not
            # sampled. Most won't clear it (same coverage limit as the
            # population at large), falling back to "unknown" like anyone
            # else.
            bluff_tier_a = _load_bluff_tier_lookup("a").get(profile["player"], "unknown")
            bluff_tier_c = _load_bluff_tier_lookup("c").get(profile["player"], "unknown")
            length = sample_session_length(archetype, self.rng)
            occ = SeatOccupant(archetype, length, freq_tier, bluff_tier_a, bluff_tier_c, profile_id=profile_id)
            self.occupants[seat] = occ
            return occ

        pool = self.allowed_archetypes
        archetype = self.rng.choices(
            pool,
            weights=[ARCHETYPE_POPULATION_WEIGHTS[a] for a in pool],
        )[0]
        freq_tier = self.forced_freq_tier.get(seat, sample_freq_tier(archetype, self.rng))
        bluff_tier_a = sample_bluff_tier(BLUFF_TIER_A_WEIGHTS, self.rng)
        bluff_tier_c = sample_bluff_tier(BLUFF_TIER_C_WEIGHTS, self.rng)
        length = sample_session_length(archetype, self.rng)
        occ = SeatOccupant(archetype, length, freq_tier, bluff_tier_a, bluff_tier_c)
        self.occupants[seat] = occ
        return occ

    def archetype_for(self, seat: int) -> str:
        return self.occupants[seat].archetype

    def freq_tier_for(self, seat: int) -> str:
        return self.occupants[seat].freq_tier

    def bluff_tier_a_for(self, seat: int) -> str:
        return self.occupants[seat].bluff_tier_a

    def bluff_tier_c_for(self, seat: int) -> str:
        return self.occupants[seat].bluff_tier_c

    def profile_id_for(self, seat: int) -> str | None:
        return self.occupants[seat].profile_id

    def hands_played_for(self, seat: int) -> int:
        """How many hands this seat's CURRENT occupant has played since
        being seated -- already tracked for turnover/session-length
        purposes, reused as-is for Tier 6's confidence-in-archetype-read
        idea (see abc_bot.py's CONFIDENCE_GATED_ARCHETYPE_READ comment).
        Resets to 0 whenever a new occupant is seated, matching "hero
        hasn't watched this specific opponent long enough yet to trust
        the read"."""
        return self.occupants[seat].hands_played

    def tilt_tier_for(self, seat: int) -> str:
        return _tilt_tier_from_hands_since(self.occupants[seat].hands_since_cooler)

    def force_tilt(self, seat: int, tier: str) -> None:
        """Telegram bot drill mode (2026-08-26): directly sets a seat's
        hands_since_cooler to a value that reads back as `tier` via
        _tilt_tier_from_hands_since's existing thresholds, so a rule gated
        on tilt (WIDER_CALL_VS_TILTING_OPPONENT) can be drilled without
        waiting for a real cooler hand to occur naturally. `tier="none"`
        clears it back to untilted."""
        mapping = {"acute": 1, "fading": 3, "residual": 6, "none": None}
        self.occupants[seat].hands_since_cooler = mapping[tier]

    def record_hand_played(self) -> None:
        """Call once per finished hand to increment every occupied seat's
        hands_played counter -- WITHOUT the reseat-on-session-length/
        bust logic after_hand() also does. probe_chance_enumeration.py
        never calls the full after_hand() (archetype identity stays
        static per seat for a whole probe run, by design), so
        hands_played would otherwise stay frozen at 0 forever and
        CONFIDENCE_GATED_ARCHETYPE_READ could never see a "trusted"
        opponent. Safe to call alongside record_hand_for_tilt -- neither
        touches the other's state."""
        for occ in self.occupants.values():
            occ.hands_played += 1

    def record_hand_for_tilt(self, hand) -> None:
        """Call once per finished hand, with the just-finished Hand object,
        to update each occupied seat's post-cooler window -- the one piece
        of session HISTORY this class tracks (everything else here is a
        static per-seat label drawn at seating time). Independent of
        after_hand()/turnover -- call this first if a seat is about to be
        replaced, since a busted seat's tilt state is moot either way.

        Cooler definition matches check_tilt_after_cooler.py exactly: this
        seat put in >=COOLER_MIN_BB, the hand reached a real showdown (not
        everyone else just folding -- Hand.finish() leaves
        result.winners_by_pot empty for an uncontested win), and this seat
        won nothing from it.
        """
        result = getattr(hand, "result", None)
        real_showdown = bool(result and result.winners_by_pot)
        payouts = result.payouts if result else {}
        big_blind = getattr(hand, "big_blind", 0)
        for seat, occ in self.occupants.items():
            player = hand.players.get(seat)
            if player is None or not getattr(player, "in_hand", False) or big_blind <= 0:
                continue
            contributed_bb = player.total_contributed / big_blind
            lost_a_cooler = real_showdown and contributed_bb >= COOLER_MIN_BB and payouts.get(seat, 0.0) <= 0.0
            if lost_a_cooler:
                occ.hands_since_cooler = 1
            elif occ.hands_since_cooler is not None:
                occ.hands_since_cooler += 1
                if occ.hands_since_cooler > POST_COOLER_WINDOW:
                    occ.hands_since_cooler = None

    def after_hand(self, seat_stacks: dict[int, float], starting_stack: float) -> dict[int, bool]:
        """Call once per finished hand with each bot seat's current stack.
        Returns {seat: did_this_seat_turn_over} so the API layer can reset
        that seat's dossier and re-seat the stack.
        """
        turned_over = {}
        for seat, occ in self.occupants.items():
            occ.hands_played += 1
            busted = seat_stacks.get(seat, 0.0) <= 0
            if occ.should_leave(busted):
                self._seat_new_occupant(seat)
                turned_over[seat] = True
            else:
                turned_over[seat] = False
        return turned_over
