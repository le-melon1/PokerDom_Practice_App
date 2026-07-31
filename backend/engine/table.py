"""Runs a sequence of hands at one table: seats players, rotates the button,
starts a new Hand each time. Player join/leave (Phase B) will call
add_player/remove_player between hands; this class just enforces "only
between hands".
"""

from backend.engine.hand import Hand
from backend.engine.models import Player


class Table:
    def __init__(
        self,
        small_blind: float,
        big_blind: float,
        max_seats: int = 8,
        rake_percent: float = 0.0,
        rake_cap_bb: float = 0.0,
    ):
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.max_seats = max_seats
        self.rake_percent = rake_percent
        self.rake_cap_bb = rake_cap_bb
        self.players: dict[int, Player] = {}
        self.button_seat: int | None = None
        self.current_hand: Hand | None = None
        self.hand_count = 0
        self.total_rake_collected = 0.0

    def add_player(self, seat: int, name: str, stack: float) -> None:
        if self.current_hand is not None and not self.current_hand.finished:
            raise RuntimeError("cannot seat a player mid-hand")
        if seat in self.players:
            raise ValueError(f"seat {seat} already occupied")
        if not (1 <= seat <= self.max_seats):
            raise ValueError(f"seat {seat} out of range")
        self.players[seat] = Player(seat=seat, name=name, stack=stack)

    def remove_player(self, seat: int) -> None:
        if self.current_hand is not None and not self.current_hand.finished:
            raise RuntimeError("cannot remove a player mid-hand")
        self.players.pop(seat, None)

    def _next_button(self) -> int:
        seats = sorted(self.players)
        if self.button_seat is None or self.button_seat not in seats:
            return seats[0]
        idx = seats.index(self.button_seat)
        return seats[(idx + 1) % len(seats)]

    def start_new_hand(self) -> Hand:
        # Busted players (stack == 0) must sit out -- otherwise they'd still get
        # dealt in, occupy a blind slot, and shift the rest of the table's
        # rotation, even though they have no chips to actually play with.
        for p in self.players.values():
            if p.stack <= 0:
                p.sitting_out = True

        active = [p for p in self.players.values() if not p.sitting_out]
        if len(active) < 2:
            raise RuntimeError("need at least 2 players with chips to start a hand")

        self.button_seat = self._next_button()
        for p in self.players.values():
            p.folded = False
            p.all_in = False
            p.hole_cards = []
            p.street_contributed = 0.0
            p.total_contributed = 0.0

        self.current_hand = Hand(
            players=list(self.players.values()),
            button_seat=self.button_seat,
            small_blind=self.small_blind,
            big_blind=self.big_blind,
            rake_percent=self.rake_percent,
            rake_cap_bb=self.rake_cap_bb,
        )
        self.hand_count += 1
        return self.current_hand

    def record_rake(self, amount: float) -> None:
        self.total_rake_collected += amount
