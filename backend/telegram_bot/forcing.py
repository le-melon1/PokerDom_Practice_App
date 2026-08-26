"""Scenario-forcing primitives for drill mode, adapted from the offline
statistical harness's own forcing techniques (scripts/probe_chance_
enumeration.py's _pick_hero_hand_swap/_apply_hero_hand_swap and
_should_force_opponent_reraise/_force_reraise_action) -- reimplemented here
rather than imported, since that script is a CLI batch-testing tool with
argparse/chunking baggage that has no place in a live bot process. The core
mechanics (swap a seat's dealt hole cards for cards still in the deck that
match a target notation set; move a chosen card to the front of the deck;
substitute a forced action instead of asking the trained model) are
unchanged -- only the hand_index/base_seed-based determinism (meaningless
in a persistent live session) is replaced with a plain random.Random.
"""

import random

from backend.bots import abc_bot
from backend.bots.behavior_clone import _POSITION_LABELS, _seat_position
from backend.engine.cards_import import Card
from backend.engine.hand import Hand
from backend.engine.table import Table

# Same real, standard-theory "hand strong enough to 4-bet with" set the
# probe script settled on after finding that forcing the ACTION alone (with
# an untouched, arbitrary hand) produced an unrealistically weak reraising
# range -- see that script's OPPONENT_RERAISE_HAND_SET comment for the full
# story (a smoke test without card-forcing measured deltas in the
# thousands of bb/100, not real).
OPPONENT_RERAISE_HAND_SET = abc_bot.VALUE_3BET_WIDE


def pick_hand_swap(
    hand: Hand, notations: set[str], rng: random.Random, seat: int
) -> tuple[list[str], list[str]] | None:
    """Finds a replacement for `seat`'s already-dealt hole cards matching one
    of `notations` (e.g. {"QQ","AKs","AKo"}), sourced from the remaining,
    undealt deck. Returns (new_hole_card_strs, old_hole_card_strs) without
    mutating anything. Returns None if no card in the remaining deck can
    complete any target notation (rare, but possible once enough cards are
    already dealt to other seats)."""
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


def apply_hand_swap(hand: Hand, new_cards: list[str], old_cards: list[str], seat: int) -> None:
    """Applies an exact swap (by card string) computed by pick_hand_swap."""
    remaining = hand.deck.cards
    for card_str in new_cards:
        for i, card in enumerate(remaining):
            if str(card) == card_str:
                remaining.pop(i)
                break
    hand.players[seat].hole_cards = list(new_cards)
    remaining.extend(Card(c) for c in old_cards)


def pick_hero_position_button(table: Table, hero_seat: int, desired_position: str) -> int:
    """Returns what table.button_seat must be set to BEFORE calling
    start_new_hand() so that hand's button rotation lands hero at
    `desired_position` (e.g. "SB", "BB", "CO", "BTN"). Table.start_new_hand
    always advances the button by one seat first (Table._next_button), so
    this returns the seat immediately BEFORE the real target button in the
    rotation, not the target button itself."""
    seats = sorted(table.players)
    n = len(seats)
    labels = _POSITION_LABELS.get(n, _POSITION_LABELS[8][:n])
    desired_index = labels.index(desired_position)
    hero_index = seats.index(hero_seat)
    target_button_index = (hero_index - desired_index) % n
    pre_advance_index = (target_button_index - 1) % n
    return seats[pre_advance_index]


def _last_seat_before_hero(hand: Hand, hero_seat: int) -> int | None:
    """The seat that acts immediately before hero, in this hand's actual
    button-relative order -- the natural "whoever raises here is a late
    steal / an opener hero then gets to respond to" seat for every
    needs-an-opener drill (SB_THREEBET_OR_FOLD_VS_STEAL, BB_DEFEND_*,
    THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT alike) -- whatever
    position hero is forced into, the seat right before them in order is
    exactly the one whose open hero then needs to react to."""
    order = hand._active_seats_from_button()
    if hero_seat not in order:
        return None
    idx = order.index(hero_seat)
    return order[idx - 1] if idx > 0 else None


def should_force_clear_to_open(hand: Hand, seat: int, hero_seat: int) -> bool:
    """For force_opponent_open drills: without this, an EARLIER seat's own
    trained model might open first (e.g. UTG), which still satisfies
    "someone opened" but from the wrong position for position-specific
    drills (SB_THREEBET_OR_FOLD_VS_STEAL/BB_DEFEND_* specifically need a
    LATE-position opener). Forces every seat that acts before the
    designated opener (should_force_opponent_open's target, the seat right
    before hero) to fold, so the scenario triggers reliably instead of
    only when the earlier seats happen to check/fold on their own."""
    if hand.street != "preflop" or hand.finished:
        return False
    preflop = [a for a in hand.actions if a.street == "preflop"]
    if any(a.action == "raises" for a in preflop):
        return False
    target = _last_seat_before_hero(hand, hero_seat)
    if target is None or seat == target:
        return False
    return hand.current_actor() == seat


def force_fold_action(hand: Hand, seat: int) -> tuple[str, float | None]:
    return "fold", None


def should_force_opponent_open(hand: Hand, seat: int, hero_seat: int) -> bool:
    """True when `seat` is the seat immediately before hero in action order,
    it's preflop, nobody has raised yet, and it's genuinely their turn --
    the drill-mode equivalent of "force someone to open the pot so hero
    gets to react to it," needed by every rule gated on facing an
    opponent's raise (steal, iso, defend) rather than on hero's own hand."""
    if hand.street != "preflop" or hand.finished:
        return False
    preflop = [a for a in hand.actions if a.street == "preflop"]
    if any(a.action == "raises" for a in preflop):
        return False
    return hand.current_actor() == seat and _last_seat_before_hero(hand, hero_seat) == seat


def force_open_action(hand: Hand, seat: int) -> tuple[str, float | None]:
    legal = hand.legal_actions(seat)
    target = hand.big_blind * 2.5
    amount = max(legal["min_raise_to"], min(target, legal["max_raise_to"]))
    return "raise", amount


def should_force_opponent_limp(hand: Hand, seat: int, hero_seat: int) -> bool:
    """Same idea as should_force_opponent_open, but for TIGHT_BIG_ISO_RAISE_
    LIMPERS/LIMP_BEHIND_OVER_LIMPERS, which need an opponent to LIMP (call
    the big blind) before hero acts, not raise."""
    if hand.street != "preflop" or hand.finished:
        return False
    preflop = [a for a in hand.actions if a.street == "preflop"]
    if any(a.action in ("raises", "bets") for a in preflop):
        return False
    return hand.current_actor() == seat and _last_seat_before_hero(hand, hero_seat) == seat


def force_limp_action(hand: Hand, seat: int) -> tuple[str, float | None]:
    legal = hand.legal_actions(seat)
    return ("check", None) if legal["can_check"] else ("call", None)


def should_force_clear_for_hero_open(hand: Hand, seat: int, hero_seat: int) -> bool:
    """For force_opponent_reraise drills (SHOVE_AA_KK_VS_3BET_PLUS): the
    reraise-forcing guard below only fires when hero's own raise is the
    exact FIRST preflop raise -- if an earlier seat opens naturally before
    hero even acts, hero's response becomes a 3-bet (not an open), and the
    n_raises==1 guard correctly refuses to force a further raise (avoiding
    a raise war), but that also means the drill's target spot (hero facing
    a 3-bet/4-bet) never gets set up. Forces every seat that acts before
    hero, preflop, before any raise, to fold -- so hero reliably gets to
    open first with the forced premium hand."""
    if hand.street != "preflop" or hand.finished:
        return False
    preflop = [a for a in hand.actions if a.street == "preflop"]
    if any(a.action == "raises" for a in preflop):
        return False
    order = hand._active_seats_from_button()
    if hero_seat not in order or seat not in order:
        return False
    if order.index(seat) >= order.index(hero_seat):
        return False
    return hand.current_actor() == seat


def should_force_opponent_reraise(hand: Hand, seat: int, hero_seat: int) -> bool:
    """True when `seat` is facing exactly hero's own preflop raise -- the
    spot SHOVE_AA_KK_VS_3BET_PLUS needs to drill (hero facing a 3-bet+).
    Fires at most once per hand (only on hero's raise being the exact FIRST
    preflop raise) -- without that guard a forced reraise puts hero's raise
    back on top, re-matching this same condition and cascading into an
    unbounded raise war (this exact bug, and the fix, already happened once
    in this project's own offline probe harness)."""
    if hand.street != "preflop" or hand.finished:
        return False
    preflop = [a for a in hand.actions if a.street == "preflop"]
    if not preflop or preflop[-1].action != "raises" or preflop[-1].seat != hero_seat:
        return False
    n_raises = sum(1 for a in preflop if a.action == "raises")
    if n_raises != 1:
        return False
    return hand.current_actor() == seat


def force_reraise_action(hand: Hand, seat: int, rng: random.Random) -> tuple[str, float | None]:
    swap = pick_hand_swap(hand, OPPONENT_RERAISE_HAND_SET, rng, seat)
    if swap is not None:
        new_cards, old_cards = swap
        apply_hand_swap(hand, new_cards, old_cards, seat)
    legal = hand.legal_actions(seat)
    return "raise", legal["min_raise_to"]
