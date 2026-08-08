"""Single-hand state machine: blinds, four betting rounds, side pots, showdown.

Raise amounts are "raise-to" (total street contribution after the action),
matching the convention already used throughout the analysis project's
parsers -- keeps this codebase consistent with the data it's trained on.
"""

from collections import deque
from dataclasses import dataclass, field

from backend.engine.cards_import import Card, Deck, evaluate_7cards
from backend.engine.models import ActionRecord, Player

STREETS = ("preflop", "flop", "turn", "river")
BOARD_LEN = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}


class IllegalAction(Exception):
    pass


@dataclass
class SidePot:
    amount: float
    eligible_seats: set[int]


@dataclass
class HandResult:
    winners_by_pot: list[tuple[SidePot, list[int]]]  # (pot, winning seats, split evenly)
    payouts: dict[int, float]  # seat -> amount won
    rake: float = 0.0


class Hand:
    def __init__(
        self,
        players: list[Player],
        button_seat: int,
        small_blind: float,
        big_blind: float,
        deck: Deck | None = None,
        rake_percent: float = 0.0,
        rake_cap_bb: float = 0.0,
    ):
        self.players = {p.seat: p for p in players}
        self.seat_order = sorted(self.players)
        self.button_seat = button_seat
        self.small_blind = small_blind
        self.big_blind = big_blind
        # Rake defaults to off (0%) so the bare engine and its tests reason about
        # exact chip conservation; the live app turns it on with PokerDom's real
        # microlimit structure (see PokerDom_Microlimits_Analysis/src/config.py:
        # RAKE_PERCENT=0.05, RAKE_CAP_BB=5.0, and "no flop, no drop").
        self.rake_percent = rake_percent
        self.rake_cap_bb = rake_cap_bb
        self.deck = deck or Deck()
        self.deck.shuffle()
        self.board: list[str] = []
        self.street_idx = 0
        self.actions: list[ActionRecord] = []
        self.current_bet = 0.0
        self.min_raise = big_blind
        self.to_act: deque[int] = deque()
        self.street_order: list[int] = []
        self.last_full_raise_seat: int | None = None
        self.finished = False
        self.result: HandResult | None = None

        self._deal_hole_cards()
        self._post_blinds()
        self._start_betting_round(is_preflop=True)

    # ---- setup ----

    def _active_seats_from_button(self) -> list[int]:
        """Seats in action order starting at the button, excluding anyone
        sitting out. Every blind/first-to-act/betting-order computation in
        this class relies on index positions here (0=button, 1=SB, 2=BB,
        3=first-to-act preflop) -- a sitting-out seat left in this list
        would shift those indices and hand the blinds to the wrong players.
        """
        seats = [s for s in self.seat_order if not self.players[s].sitting_out]
        if self.button_seat not in seats:
            return seats
        btn_idx = seats.index(self.button_seat)
        return seats[btn_idx:] + seats[:btn_idx]

    def _deal_hole_cards(self) -> None:
        for seat in self._active_seats_from_button():
            player = self.players[seat]
            player.hole_cards = [str(c) for c in self.deck.draw(2)]

    def _post_blinds(self) -> None:
        rotation = self._active_seats_from_button()
        if len(rotation) == 2:
            sb_seat, bb_seat = rotation[0], rotation[1]  # heads-up: button posts SB
        else:
            sb_seat, bb_seat = rotation[1], rotation[2]

        self._post(sb_seat, self.small_blind)
        self.actions.append(ActionRecord(self.street, sb_seat, "small_blind", self.small_blind))
        self._post(bb_seat, self.big_blind)
        self.actions.append(ActionRecord(self.street, bb_seat, "big_blind", self.big_blind))
        self.current_bet = self.big_blind

    def _post(self, seat: int, amount: float) -> None:
        player = self.players[seat]
        amount = min(amount, player.stack)
        player.stack -= amount
        player.street_contributed += amount
        player.total_contributed += amount
        if player.stack == 0:
            player.all_in = True

    def _start_betting_round(self, is_preflop: bool) -> None:
        rotation = self._active_seats_from_button()
        if is_preflop:
            # action starts left of BB (index 3: button, SB, BB, then first-to-act);
            # heads-up the button (SB) acts first
            order = rotation if len(rotation) == 2 else rotation[3:] + rotation[:3]
        else:
            # postflop: first active seat *after* the button acts first, button acts
            # last (heads-up: BB acts first, button/SB acts last) -- `rotation` starts
            # AT the button, so rotate it by one to move the button to the back.
            order = rotation[1:] + rotation[:1]
        order = [s for s in order if self.players[s].in_hand]
        self.street_order = order  # canonical action order for this street, kept even
        # after a bet/raise reopens the round -- see apply_action's bet/raise branch
        self.to_act = deque(s for s in order if self.players[s].can_act)
        self.last_full_raise_seat = None

    # ---- querying ----

    @property
    def street(self) -> str:
        return STREETS[self.street_idx]

    def current_actor(self) -> int | None:
        return self.to_act[0] if self.to_act else None

    def legal_actions(self, seat: int) -> dict:
        player = self.players[seat]
        to_call = self.current_bet - player.street_contributed
        min_raise_to = self.current_bet + self.min_raise
        return {
            "can_check": to_call <= 0,
            "can_call": to_call > 0,
            "call_amount": max(0.0, min(to_call, player.stack)),
            "min_raise_to": min(min_raise_to, player.street_contributed + player.stack),
            "max_raise_to": player.street_contributed + player.stack,
        }

    def _players_still_live(self) -> list[Player]:
        return [p for p in self.players.values() if p.in_hand]

    # ---- actions ----

    def apply_action(self, seat: int, action: str, amount: float | None = None) -> None:
        if self.finished:
            raise IllegalAction("hand already finished")
        if not self.to_act or self.to_act[0] != seat:
            raise IllegalAction(f"it is not seat {seat}'s turn")

        player = self.players[seat]
        legal = self.legal_actions(seat)

        if action == "fold":
            player.folded = True
            self.actions.append(ActionRecord(self.street, seat, "folds"))
            self.to_act.popleft()

        elif action == "check":
            if not legal["can_check"]:
                raise IllegalAction("cannot check facing a bet")
            self.actions.append(ActionRecord(self.street, seat, "checks"))
            self.to_act.popleft()

        elif action == "call":
            call_amount = legal["call_amount"]
            player.stack -= call_amount
            player.street_contributed += call_amount
            player.total_contributed += call_amount
            if player.stack == 0:
                player.all_in = True
            self.actions.append(ActionRecord(self.street, seat, "calls", call_amount))
            self.to_act.popleft()

        elif action in ("bet", "raise"):
            if amount is None:
                raise IllegalAction("bet/raise requires an amount (raise-to)")
            max_to = legal["max_raise_to"]
            min_to = legal["min_raise_to"] if self.current_bet > 0 else self.big_blind
            is_all_in_shove = amount >= max_to - 1e-9
            if amount < min_to - 1e-9 and not is_all_in_shove:
                raise IllegalAction(f"raise to {amount} below minimum {min_to}")
            amount = min(amount, max_to)

            current_bet_before = self.current_bet
            increment = amount - player.street_contributed
            player.stack -= increment
            player.street_contributed = amount
            player.total_contributed += increment
            if player.stack <= 1e-9:
                player.all_in = True

            was_full_raise = amount - current_bet_before >= self.min_raise - 1e-9
            if was_full_raise:
                self.min_raise = amount - current_bet_before
            # A short all-in (amount < current_bet_before) doesn't lower the price
            # everyone else owes -- it just means this player is all-in for less
            # and a side pot forms; current_bet must never decrease.
            self.current_bet = max(current_bet_before, amount)

            # postflop with nothing bet yet = "bets"; anything on top of an existing bet
            # (postflop), or any preflop aggression on top of the blinds, = "raises"
            kind = "bets" if (self.street != "preflop" and current_bet_before == 0) else "raises"
            self.actions.append(ActionRecord(self.street, seat, kind, increment))

            self.to_act.popleft()
            # Any bet/raise (including a short all-in raise) makes every other live,
            # not-all-in player owe a fresh decision -- simpler than exactly modeling
            # the casino-rule nuance where a short all-in doesn't reopen betting for
            # players who already matched the previous bet, and not exploitable here.
            # Must continue in the street's actual action order starting right after
            # the raiser -- NOT restart from a button-first rotation, which used to
            # let players who act later than the raiser (e.g. the button, or blinds
            # on a later street) jump the queue ahead of players still owed a turn.
            idx = self.street_order.index(seat)
            rotated = self.street_order[idx + 1:] + self.street_order[: idx + 1]
            others = [s for s in rotated if self.players[s].can_act and s != seat]
            self.to_act = deque(others)
        else:
            raise IllegalAction(f"unknown action {action}")

        self._advance_if_round_over()

    # ---- street / hand progression ----

    def _advance_if_round_over(self) -> None:
        live = self._players_still_live()
        if len(live) <= 1:
            self._finish_hand()
            return

        if self.to_act:
            return

        if all(p.all_in or not p.can_act for p in live) and self.street_idx < len(STREETS) - 1:
            self._run_out_remaining_streets()
            return

        if self.street_idx == len(STREETS) - 1:
            self._finish_hand()
        else:
            self._advance_street()

    def _advance_street(self) -> None:
        self.street_idx += 1
        for p in self.players.values():
            p.street_contributed = 0.0
        self.current_bet = 0.0
        self.min_raise = self.big_blind
        self._deal_board(BOARD_LEN[self.street])
        self._start_betting_round(is_preflop=False)
        if not self.to_act:
            self._advance_if_round_over()

    def _run_out_remaining_streets(self) -> None:
        while self.street_idx < len(STREETS) - 1:
            self.street_idx += 1
            self._deal_board(BOARD_LEN[self.street])
        self._finish_hand()

    def _deal_board(self, target_len: int) -> None:
        while len(self.board) < target_len:
            self.board.append(str(self.deck.draw(1)[0]))

    # ---- showdown / side pots ----

    def _compute_rake(self, total_pot: float) -> float:
        # "No flop, no drop": a pot that never saw a flop (everyone folded
        # preflop) isn't raked, matching real cardroom practice and the
        # PokerDom rake structure this app models.
        if self.street_idx == 0 or total_pot <= 0:
            return 0.0
        cap = self.rake_cap_bb * self.big_blind
        rake = total_pot * self.rake_percent
        return min(rake, cap) if cap > 0 else rake

    def _finish_hand(self) -> None:
        self.finished = True
        live = self._players_still_live()
        total_pot = sum(p.total_contributed for p in self.players.values())
        nominal_rake = self._compute_rake(total_pot)

        if len(live) == 1:
            winner = live[0]
            net = total_pot - nominal_rake
            winner.stack += net
            self.result = HandResult(winners_by_pot=[], payouts={winner.seat: net}, rake=nominal_rake)
            return

        while len(self.board) < 5:
            self.board.append(str(self.deck.draw(1)[0]))

        pots = self._build_side_pots()
        rake_ratio = nominal_rake / total_pot if total_pot > 0 else 0.0
        payouts: dict[int, float] = {}
        winners_by_pot = []
        rake_taken = 0.0

        for pot in pots:
            eligible_live = [s for s in pot.eligible_seats if self.players[s].in_hand]
            if not eligible_live:
                # Nobody who ever contributed to this side-pot LAYER is
                # still in the hand (all folded on a later street) -- there's
                # no one left to award it to via showdown, so it was never
                # actually a contested pot. The common case: a bet/raise
                # bigger than any opponent could ever call, so this layer's
                # eligible_seats has exactly one member (a real "uncalled
                # bet" that should never have been at showdown risk in the
                # first place) -- but the same fix covers the rarer case of
                # several contributors to one layer who all later fold.
                # Refund each contributor their own stake in this specific
                # layer. Never raked -- nothing was actually won here, same
                # as a real uncalled bet is never raked. Fixed 2026-08-08
                # after scripts/smoke_test_table.py caught real chip loss
                # (this layer's money previously just vanished via a bare
                # `continue`).
                refund_each = pot.amount / len(pot.eligible_seats)
                for s in pot.eligible_seats:
                    payouts[s] = payouts.get(s, 0.0) + refund_each
                    self.players[s].stack += refund_each
                continue
            scores = {s: evaluate_7cards([Card(c) for c in self.players[s].hole_cards] + [Card(c) for c in self.board]) for s in eligible_live}
            best = max(scores.values())
            pot_winners = [s for s, v in scores.items() if v == best]
            pot_rake = pot.amount * rake_ratio
            net_amount = pot.amount - pot_rake
            rake_taken += pot_rake
            share = net_amount / len(pot_winners)
            for s in pot_winners:
                payouts[s] = payouts.get(s, 0.0) + share
                self.players[s].stack += share
            winners_by_pot.append((pot, pot_winners))

        self.result = HandResult(winners_by_pot=winners_by_pot, payouts=payouts, rake=rake_taken)

    def _build_side_pots(self) -> list[SidePot]:
        contributions = {s: p.total_contributed for s, p in self.players.items() if p.total_contributed > 0}
        levels = sorted(set(contributions.values()))
        pots = []
        prev_level = 0.0
        for level in levels:
            layer = level - prev_level
            contributors = [s for s, c in contributions.items() if c >= level - 1e-9]
            if layer > 1e-9 and contributors:
                pots.append(SidePot(amount=layer * len(contributors), eligible_seats=set(contributors)))
            prev_level = level
        return pots
