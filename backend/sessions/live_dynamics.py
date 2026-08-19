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
    def __init__(self, archetype: str, planned_length: int, profile_id: str | None = None):
        self.archetype = archetype
        self.planned_length = planned_length
        self.hands_played = 0
        # None in normal archetype mode. When set, this seat is a "real
        # player" bot (see backend/bots/player_profile_bots.py) instead of
        # the population-wide archetype model -- hands_played doubles as
        # that model's session_hands_so_far feature, the exact same causal
        # quantity build_player_profile_training_data.py computed it as.
        self.profile_id = profile_id

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
    instead of the population-wide archetype model."""

    def __init__(
        self,
        bot_seats: list[int],
        rng_seed: int | None = None,
        allowed_archetypes: list[str] | None = None,
        player_profile_ids: list[str] | None = None,
    ):
        self.rng = random.Random(rng_seed)
        self.allowed_archetypes = [a for a in ARCHETYPE_POOL if a in allowed_archetypes] if allowed_archetypes else list(ARCHETYPE_POOL)
        if not self.allowed_archetypes:
            self.allowed_archetypes = list(ARCHETYPE_POOL)
        self.player_profile_ids = list(player_profile_ids) if player_profile_ids else None
        self.occupants: dict[int, SeatOccupant] = {}
        for seat in bot_seats:
            self._seat_new_occupant(seat)

    def _seat_new_occupant(self, seat: int) -> SeatOccupant:
        if self.player_profile_ids:
            from backend.bots.player_profile_bots import load_profile_pool

            profile_id = self.rng.choice(self.player_profile_ids)
            archetype = load_profile_pool()[profile_id]["archetype"]
            length = sample_session_length(archetype, self.rng)
            occ = SeatOccupant(archetype, length, profile_id=profile_id)
            self.occupants[seat] = occ
            return occ

        pool = self.allowed_archetypes
        archetype = self.rng.choices(
            pool,
            weights=[ARCHETYPE_POPULATION_WEIGHTS[a] for a in pool],
        )[0]
        length = sample_session_length(archetype, self.rng)
        occ = SeatOccupant(archetype, length)
        self.occupants[seat] = occ
        return occ

    def archetype_for(self, seat: int) -> str:
        return self.occupants[seat].archetype

    def profile_id_for(self, seat: int) -> str | None:
        return self.occupants[seat].profile_id

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
