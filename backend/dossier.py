"""Session-scoped dossier: VPIP/PFR/3-bet/aggression + a style label, counted
only from hands played at THIS table since the bot sat down -- resets when a
bot leaves and a new one takes the seat. Shown from hand 1 (no minimum-sample
gate), matching how the real PokerDom UI in the reference screenshot displays
stats immediately rather than waiting for a reliability threshold -- unlike
the offline analysis project's archetypes.py, which gates on 100 hands
because it's making population-level claims, not a live in-session read.

Style-label thresholds are a simplified port of the analysis project's
pipeline/archetypes.py::_label_row so the wording stays consistent with the
"Nit/TAG/LAG/Loose-passive/Station/Maniac" labels used everywhere else in
this project.
"""

from dataclasses import dataclass, field

from backend.bots.behavior_clone import _POSITION_LABELS
from backend.engine.hand import Hand


def _style_label(vpip: float, pfr: float, af: float) -> str:
    pfr_ratio = pfr / vpip if vpip > 0 else 0.0
    if vpip < 0.15:
        return "Nit"
    if vpip > 0.45 and af >= 2.0:
        return "Maniac"
    if vpip > 0.35 and pfr_ratio < 0.35:
        return "Station"
    if pfr_ratio >= 0.6 and vpip <= 0.28:
        return "TAG"
    if pfr_ratio >= 0.45:
        return "LAG"
    return "Loose-passive"


@dataclass
class SeatDossier:
    hands_seen: int = 0
    vpip_hands: int = 0
    pfr_hands: int = 0
    threebet_hands: int = 0
    aggressive_postflop: int = 0
    passive_postflop: int = 0
    net_won: float = 0.0
    position_vpip: dict[str, int] = field(default_factory=dict)
    position_pfr: dict[str, int] = field(default_factory=dict)
    postflop_aggression: dict[str, int] = field(default_factory=dict)
    postflop_passivity: dict[str, int] = field(default_factory=dict)
    river_aggression_showdowns: int = 0
    river_aggression_showdown_losses: int = 0

    def __setstate__(self, state: dict) -> None:
        """Backwards-compatible unpickle support.

        Older saved app state may contain SeatDossier objects serialized before
        context fields were introduced. When such objects are restored, ensure
        new fields are present so live requests don't crash.
        """
        self.__dict__.update(state)
        self.ensure_compat()

    def ensure_compat(self) -> None:
        if not hasattr(self, "position_vpip") or self.position_vpip is None:
            self.position_vpip = {}
        if not hasattr(self, "position_pfr") or self.position_pfr is None:
            self.position_pfr = {}
        if not hasattr(self, "postflop_aggression") or self.postflop_aggression is None:
            self.postflop_aggression = {}
        if not hasattr(self, "postflop_passivity") or self.postflop_passivity is None:
            self.postflop_passivity = {}
        if not hasattr(self, "river_aggression_showdowns") or self.river_aggression_showdowns is None:
            self.river_aggression_showdowns = 0
        if not hasattr(self, "river_aggression_showdown_losses") or self.river_aggression_showdown_losses is None:
            self.river_aggression_showdown_losses = 0

    @property
    def vpip(self) -> float:
        return self.vpip_hands / self.hands_seen if self.hands_seen else 0.0

    @property
    def pfr(self) -> float:
        return self.pfr_hands / self.hands_seen if self.hands_seen else 0.0

    @property
    def threebet_pct(self) -> float:
        return self.threebet_hands / self.hands_seen if self.hands_seen else 0.0

    @property
    def afq(self) -> float:
        total = self.aggressive_postflop + self.passive_postflop
        return self.aggressive_postflop / total if total else 0.0

    @property
    def river_bluff_rate(self) -> float:
        """Share of this seat's river-aggression-that-reached-a-real-showdown
        hands they LOST -- the live, session-scoped, causal analogue of
        PokerDom_Microlimits_Analysis's find_frequent_bluffers.py (same
        "river aggressor loses at real showdown" proxy, same disclosed
        limitation: conflates pure air bluffs with thin value bets that lost,
        and can only ever see a bluff that got TO showdown, not one that won
        via a fold). That script needed >=40 river showdowns per player to
        trust a LONG-RUN population label; a single live session will never
        reach that, so see HERO_BLUFFER_MIN_RIVER_SHOWDOWNS in
        behavior_clone.py for the much smaller in-session threshold this
        feeds into instead."""
        return (
            self.river_aggression_showdown_losses / self.river_aggression_showdowns
            if self.river_aggression_showdowns
            else 0.0
        )

    @property
    def style(self) -> str:
        af_ratio = (
            self.aggressive_postflop / self.passive_postflop
            if self.passive_postflop
            else float(self.aggressive_postflop > 0) * 2
        )
        return _style_label(self.vpip, self.pfr, af_ratio)


class TableDossier:
    """One SeatDossier per seat, reset whenever a new occupant sits down."""

    def __init__(self):
        self.by_seat: dict[int, SeatDossier] = {}

    def reset_seat(self, seat: int) -> None:
        self.by_seat[seat] = SeatDossier()

    def _position_label(self, hand: Hand, seat: int) -> str:
        # 2026-08: this used to keep its own copy of the position-label table,
        # truncated at 5 seats -- crashed with IndexError on any 6-8max hand
        # (the practice app's actual default table size). Reuse
        # behavior_clone.py's full table instead of re-duplicating it.
        order = hand._active_seats_from_button()
        labels = _POSITION_LABELS.get(len(order), _POSITION_LABELS[8][: len(order)])
        try:
            return labels[order.index(seat)]
        except ValueError:
            return "MP"

    def record_hand(self, hand: Hand) -> None:
        vpip_seats: set[int] = set()
        pfr_seats: set[int] = set()
        threebet_seats: set[int] = set()
        raises_seen_preflop = 0

        for a in hand.actions:
            if a.street != "preflop":
                continue
            if a.action in ("calls", "bets", "raises"):
                vpip_seats.add(a.seat)
            if a.action == "raises":
                (pfr_seats if raises_seen_preflop == 0 else threebet_seats).add(a.seat)
                raises_seen_preflop += 1

        for a in hand.actions:
            if a.street == "preflop":
                continue
            dossier = self.by_seat.setdefault(a.seat, SeatDossier())
            dossier.ensure_compat()
            if a.action in ("bets", "raises"):
                dossier.aggressive_postflop += 1
                dossier.postflop_aggression[a.street] = dossier.postflop_aggression.get(a.street, 0) + 1
            elif a.action == "calls":
                dossier.passive_postflop += 1
                dossier.postflop_passivity[a.street] = dossier.postflop_passivity.get(a.street, 0) + 1

        for seat, player in hand.players.items():
            if player.sitting_out:
                continue  # wasn't actually dealt into this hand
            dossier = self.by_seat.setdefault(seat, SeatDossier())
            dossier.ensure_compat()
            dossier.hands_seen += 1
            position = self._position_label(hand, seat)
            if seat in vpip_seats:
                dossier.vpip_hands += 1
                dossier.position_vpip[position] = dossier.position_vpip.get(position, 0) + 1
            if seat in pfr_seats:
                dossier.pfr_hands += 1
                dossier.position_pfr[position] = dossier.position_pfr.get(position, 0) + 1
            if seat in threebet_seats:
                dossier.threebet_hands += 1

        if hand.result:
            for seat, amount in hand.result.payouts.items():
                dossier = self.by_seat.setdefault(seat, SeatDossier())
                dossier.ensure_compat()
                invested = hand.players[seat].total_contributed
                dossier.net_won += amount - invested

            # Live analogue of find_frequent_bluffers.py: the LAST bets/raises
            # action on the river ("whoever showed strength last"), IF the
            # hand actually reached a real, contested multi-way showdown
            # (winners_by_pot is only populated by that code path -- the
            # single-live-player early return in Hand._finish_hand leaves it
            # empty, correctly excluding uncalled-bet wins, which aren't a
            # showdown at all). "Lost" = won no share of any pot, same
            # is_winner-based definition the offline script uses.
            river_aggressor = None
            for a in hand.actions:
                if a.street == "river" and a.action in ("bets", "raises"):
                    river_aggressor = a.seat
            if river_aggressor is not None and hand.result.winners_by_pot:
                dossier = self.by_seat.setdefault(river_aggressor, SeatDossier())
                dossier.ensure_compat()
                dossier.river_aggression_showdowns += 1
                if hand.result.payouts.get(river_aggressor, 0.0) <= 0.0:
                    dossier.river_aggression_showdown_losses += 1
