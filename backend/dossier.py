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
            if a.action in ("bets", "raises"):
                dossier.aggressive_postflop += 1
            elif a.action == "calls":
                dossier.passive_postflop += 1

        for seat, player in hand.players.items():
            if player.sitting_out:
                continue  # wasn't actually dealt into this hand
            dossier = self.by_seat.setdefault(seat, SeatDossier())
            dossier.hands_seen += 1
            if seat in vpip_seats:
                dossier.vpip_hands += 1
            if seat in pfr_seats:
                dossier.pfr_hands += 1
            if seat in threebet_seats:
                dossier.threebet_hands += 1

        if hand.result:
            for seat, amount in hand.result.payouts.items():
                dossier = self.by_seat.setdefault(seat, SeatDossier())
                invested = hand.players[seat].total_contributed
                dossier.net_won += amount - invested
