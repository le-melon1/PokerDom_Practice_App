from __future__ import annotations

import random
from dataclasses import dataclass, field

from backend.engine.cards_import import Card, evaluate_7cards
from src.engine.cards import RANKS, SUITS
from src.engine.range_equity import expand_hand_to_combos, filter_combos_for_board

HERO_ACTIONS = ("check", "bet_min", "bet_75", "all_in")
VILLAIN_ACTIONS = ("fold", "call")
DEFENSE_ACTIONS = ("fold", "call", "raise_min", "raise_75", "raise_all_in")
RERAISE_ACTIONS = ("fold", "call", "reraise_all_in")
ALL_IN_RESPONSE_ACTIONS = ("fold", "call")
STREETS = ("flop", "turn", "river")
STREET_BY_BOARD_LENGTH = {3: "flop", 4: "turn", 5: "river"}


@dataclass
class _InfoNode:
    player: str
    street: str
    actions: tuple[str, ...]
    regrets: dict[str, float] = field(default_factory=dict)
    strategy_sum: dict[str, float] = field(default_factory=dict)
    utility_sum: dict[str, float] = field(default_factory=dict)
    utility_samples: int = 0

    def __post_init__(self) -> None:
        self.regrets = {action: 0.0 for action in self.actions}
        self.strategy_sum = {action: 0.0 for action in self.actions}
        self.utility_sum = {action: 0.0 for action in self.actions}

    def strategy(self) -> dict[str, float]:
        positive = {action: max(0.0, self.regrets[action]) for action in self.actions}
        total = sum(positive.values())
        if total <= 0:
            return {action: 1.0 / len(self.actions) for action in self.actions}
        return {action: positive[action] / total for action in self.actions}

    def average_strategy(self) -> dict[str, float]:
        total = sum(self.strategy_sum.values())
        if total <= 0:
            return {action: 1.0 / len(self.actions) for action in self.actions}
        return {action: self.strategy_sum[action] / total for action in self.actions}

    def average_utilities(self) -> dict[str, float]:
        if self.utility_samples <= 0:
            return {action: 0.0 for action in self.actions}
        return {action: self.utility_sum[action] / self.utility_samples for action in self.actions}


def _expand_range(hands: list[str]) -> list[tuple[str, str]]:
    return [combo for hand in hands for combo in expand_hand_to_combos(hand)]


def _hand_bucket(combo: tuple[str, str], board: list[str]) -> str:
    category = evaluate_7cards([Card(combo[0]), Card(combo[1]), *[Card(card) for card in board]])[0]
    if category >= 4:
        return "strong"
    if category >= 2:
        return "medium"
    return "weak"


def _board_texture(board: list[str]) -> str:
    ranks = [card[0] for card in board]
    suits = [card[1] for card in board]
    paired = "paired" if len(set(ranks)) < len(ranks) else "unpaired"
    suit_count = max(suits.count(suit) for suit in set(suits))
    suitedness = "monotone" if suit_count >= 3 else ("two-tone" if suit_count == 2 else "rainbow")
    high_cards = sum(rank in "TJQKA" for rank in ranks)
    return f"{paired}:{suitedness}:high{min(high_cards, 2)}"


def _pot_bucket(pot: float, initial_pot: float) -> str:
    ratio = pot / initial_pot
    if ratio < 2.0:
        return "small"
    if ratio < 5.0:
        return "medium"
    return "large"


def _showdown_utility(winner: int, pot: float, hero_invested: float) -> float:
    if winner > 0:
        return pot - hero_invested
    if winner < 0:
        return -hero_invested
    return pot / 2.0 - hero_invested


def solve_postflop_subgame(
    hero_range: list[str],
    villain_range: list[str],
    board: list[str],
    pot: float,
    effective_stack: float = 100.0,
    iterations: int = 1200,
    seed: int = 17,
    focus_combo: tuple[str, str] | None = None,
    to_call: float = 0.0,
    raise_investment: float | None = None,
    min_bet_investment: float | None = None,
) -> dict:
    """Solve a compact heads-up postflop subgame with outcome-sampling CFR.

    Both private ranges are sampled as concrete blocker-aware combos. Unknown
    turn/river cards are real chance nodes. The action abstraction is intentionally
    bounded to check, 33% pot, and 75% pot; villain may fold or call, with no
    raises. Information sets share three hand-strength buckets and public-board
    textures so sampled runouts converge within a local-app time budget.
    """
    if len(board) not in STREET_BY_BOARD_LENGTH:
        raise ValueError("board must contain three, four, or five cards")
    if pot <= 0 or effective_stack <= 0 or iterations <= 0:
        raise ValueError("pot, effective_stack, and iterations must be positive")
    if to_call < 0 or to_call > effective_stack:
        raise ValueError("to_call must be between zero and effective_stack")
    if len(set(board)) != len(board):
        raise ValueError("board cards must be unique")

    start_street = STREET_BY_BOARD_LENGTH[len(board)]
    start_index = STREETS.index(start_street)

    hero_combos = filter_combos_for_board(_expand_range(hero_range), board)
    villain_combos = filter_combos_for_board(_expand_range(villain_range), board)
    if not hero_combos or not villain_combos:
        raise ValueError("both ranges must contain at least one combo compatible with the flop")

    rng = random.Random(seed)
    full_deck = [rank + suit for rank in RANKS for suit in SUITS]
    nodes: dict[str, _InfoNode] = {}
    sampled_turns: set[str] = set()
    sampled_rivers: set[str] = set()
    completed_iterations = 0
    bucket_cache: dict[tuple[tuple[str, str], tuple[str, ...]], str] = {}
    texture_cache: dict[tuple[str, ...], str] = {}
    facing_bet = to_call > 0
    resolved_min_raise = min(
        effective_stack,
        max(to_call, raise_investment if raise_investment is not None else to_call + pot * 0.75),
    )
    raise_investments = {
        "raise_min": resolved_min_raise,
        "raise_75": min(effective_stack, max(resolved_min_raise, to_call + (pot + to_call) * 0.75)),
        "raise_all_in": effective_stack,
    }

    def bet_amount(action: str, current_pot: float, hero_invested: float, street_index: int) -> float:
        remaining = max(0.0, effective_stack - hero_invested)
        if action == "all_in":
            return remaining
        if action == "bet_75":
            return min(remaining, current_pot * 0.75)
        if street_index == start_index and min_bet_investment is not None:
            return min(remaining, min_bet_investment)
        return min(remaining, current_pot * 0.33)

    def node_for(key: str, player: str, street: str, actions: tuple[str, ...]) -> _InfoNode:
        if key not in nodes:
            nodes[key] = _InfoNode(player=player, street=street, actions=actions)
        return nodes[key]

    def hand_bucket(combo: tuple[str, str], current_board: list[str]) -> str:
        key = (combo, tuple(current_board))
        if key not in bucket_cache:
            bucket_cache[key] = _hand_bucket(combo, current_board)
        return bucket_cache[key]

    def board_texture(current_board: list[str]) -> str:
        key = tuple(current_board)
        if key not in texture_cache:
            texture_cache[key] = _board_texture(current_board)
        return texture_cache[key]

    def terminal_or_next(
        street_index: int,
        boards: list[list[str]],
        winner: int,
        current_pot: float,
        hero_invested: float,
        hero_combo: tuple[str, str],
        villain_combo: tuple[str, str],
        hero_reach: float,
        villain_reach: float,
    ) -> float:
        if street_index == len(STREETS) - 1:
            return _showdown_utility(winner, current_pot, hero_invested)
        return cfr(
            street_index + 1,
            boards,
            winner,
            current_pot,
            hero_invested,
            hero_combo,
            villain_combo,
            hero_reach,
            villain_reach,
        )

    def villain_response(
        street_index: int,
        boards: list[list[str]],
        winner: int,
        current_pot: float,
        hero_invested: float,
        bet: float,
        bet_action: str,
        hero_combo: tuple[str, str],
        villain_combo: tuple[str, str],
        hero_reach: float,
        villain_reach: float,
    ) -> float:
        board = boards[street_index]
        street = STREETS[street_index]
        key = "|".join(
            (
                "V",
                street,
                hand_bucket(villain_combo, board),
                board_texture(board),
                _pot_bucket(current_pot, pot),
                bet_action,
            )
        )
        node = node_for(key, "villain", street, VILLAIN_ACTIONS)
        strategy = node.strategy()
        for action in VILLAIN_ACTIONS:
            node.strategy_sum[action] += villain_reach * strategy[action]

        utilities = {
            "fold": current_pot - hero_invested,
            "call": terminal_or_next(
                street_index,
                boards,
                winner,
                current_pot + bet,
                hero_invested,
                hero_combo,
                villain_combo,
                hero_reach,
                villain_reach * strategy["call"],
            ),
        }
        node_utility = sum(strategy[action] * utilities[action] for action in VILLAIN_ACTIONS)
        for action in VILLAIN_ACTIONS:
            node.regrets[action] += hero_reach * (node_utility - utilities[action])
        return node_utility

    def cfr(
        street_index: int,
        boards: list[list[str]],
        winner: int,
        current_pot: float,
        hero_invested: float,
        hero_combo: tuple[str, str],
        villain_combo: tuple[str, str],
        hero_reach: float,
        villain_reach: float,
    ) -> float:
        board = boards[street_index]
        street = STREETS[street_index]
        key = "|".join(
            (
                "H",
                street,
                hand_bucket(hero_combo, board),
                board_texture(board),
                _pot_bucket(current_pot, pot),
            )
        )
        node = node_for(key, "hero", street, HERO_ACTIONS)
        strategy = node.strategy()
        for action in HERO_ACTIONS:
            node.strategy_sum[action] += hero_reach * strategy[action]

        utilities: dict[str, float] = {}
        utilities["check"] = terminal_or_next(
            street_index,
            boards,
            winner,
            current_pot,
            hero_invested,
            hero_combo,
            villain_combo,
            hero_reach * strategy["check"],
            villain_reach,
        )
        for action in HERO_ACTIONS[1:]:
            bet = bet_amount(action, current_pot, hero_invested, street_index)
            if bet <= 0:
                utilities[action] = utilities["check"]
                continue
            utilities[action] = villain_response(
                street_index,
                boards,
                winner,
                current_pot + bet,
                hero_invested + bet,
                bet,
                action,
                hero_combo,
                villain_combo,
                hero_reach * strategy[action],
                villain_reach,
            )

        node_utility = sum(strategy[action] * utilities[action] for action in HERO_ACTIONS)
        for action in HERO_ACTIONS:
            node.utility_sum[action] += utilities[action]
        node.utility_samples += 1
        for action in HERO_ACTIONS:
            node.regrets[action] += villain_reach * (utilities[action] - node_utility)
        return node_utility

    def hero_vs_all_in(
        board: list[str],
        winner: int,
        current_pot: float,
        hero_invested: float,
        hero_combo: tuple[str, str],
        hero_reach: float,
        villain_reach: float,
    ) -> float:
        key = "|".join(("A", start_street, hand_bucket(hero_combo, board), board_texture(board)))
        node = node_for(key, "hero-response", start_street, ALL_IN_RESPONSE_ACTIONS)
        strategy = node.strategy()
        for action in ALL_IN_RESPONSE_ACTIONS:
            node.strategy_sum[action] += hero_reach * strategy[action]

        utilities = {
            "fold": -hero_invested,
            "call": _showdown_utility(winner, current_pot + (effective_stack - hero_invested), effective_stack),
        }
        node_utility = sum(strategy[action] * utilities[action] for action in ALL_IN_RESPONSE_ACTIONS)
        for action in ALL_IN_RESPONSE_ACTIONS:
            node.regrets[action] += villain_reach * (utilities[action] - node_utility)
        return node_utility

    def villain_vs_raise(
        boards: list[list[str]],
        winner: int,
        current_pot: float,
        hero_invested: float,
        hero_combo: tuple[str, str],
        villain_combo: tuple[str, str],
        hero_reach: float,
        villain_reach: float,
        raise_action: str,
    ) -> float:
        board = boards[start_index]
        villain_call = max(0.0, hero_invested - to_call)
        can_reraise = raise_action != "raise_all_in" and hero_invested < effective_stack - 1e-9
        actions = RERAISE_ACTIONS if can_reraise else VILLAIN_ACTIONS
        key = "|".join(
            ("R", start_street, hand_bucket(villain_combo, board), board_texture(board), raise_action)
        )
        node = node_for(key, "villain-response", start_street, actions)
        strategy = node.strategy()
        for action in actions:
            node.strategy_sum[action] += villain_reach * strategy[action]

        utilities: dict[str, float] = {
            "fold": current_pot - hero_invested,
            "call": terminal_or_next(
                start_index,
                boards,
                winner,
                current_pot + villain_call,
                hero_invested,
                hero_combo,
                villain_combo,
                hero_reach,
                villain_reach * strategy["call"],
            ),
        }
        if can_reraise:
            villain_remaining = max(0.0, effective_stack - to_call)
            pot_after_shove = current_pot + villain_remaining
            utilities["reraise_all_in"] = hero_vs_all_in(
                board,
                winner,
                pot_after_shove,
                hero_invested,
                hero_combo,
                hero_reach,
                villain_reach * strategy["reraise_all_in"],
            )

        node_utility = sum(strategy[action] * utilities[action] for action in actions)
        for action in actions:
            node.regrets[action] += hero_reach * (node_utility - utilities[action])
        return node_utility

    def facing_bet_root(
        boards: list[list[str]],
        winner: int,
        hero_combo: tuple[str, str],
        villain_combo: tuple[str, str],
    ) -> float:
        board = boards[start_index]
        key = "|".join(("D", start_street, hand_bucket(hero_combo, board), board_texture(board)))
        node = node_for(key, "hero-defense", start_street, DEFENSE_ACTIONS)
        strategy = node.strategy()
        for action in DEFENSE_ACTIONS:
            node.strategy_sum[action] += strategy[action]

        utilities: dict[str, float] = {
            "fold": 0.0,
            "call": terminal_or_next(
                start_index,
                boards,
                winner,
                pot + to_call,
                to_call,
                hero_combo,
                villain_combo,
                strategy["call"],
                1.0,
            ),
        }
        for action, investment in raise_investments.items():
            utilities[action] = villain_vs_raise(
                boards,
                winner,
                pot + investment,
                investment,
                hero_combo,
                villain_combo,
                strategy[action],
                1.0,
                action,
            )
        node_utility = sum(strategy[action] * utilities[action] for action in DEFENSE_ACTIONS)
        for action in DEFENSE_ACTIONS:
            node.utility_sum[action] += utilities[action]
            node.regrets[action] += utilities[action] - node_utility
        node.utility_samples += 1
        return node_utility

    for _ in range(iterations):
        for _ in range(50):
            hero_combo = rng.choice(hero_combos)
            villain_combo = rng.choice(villain_combos)
            used = set(board) | set(hero_combo) | set(villain_combo)
            if len(used) == len(board) + 4:
                break
        else:
            continue

        runout = rng.sample([card for card in full_deck if card not in used], 5 - len(board))
        if start_street == "flop":
            sampled_turns.add(runout[0])
            sampled_rivers.add(runout[1])
            boards = [board, board + [runout[0]], board + runout]
        elif start_street == "turn":
            sampled_rivers.add(runout[0])
            boards = [[], board, board + runout]
        else:
            boards = [[], [], board]
        board_cards = [Card(card) for card in boards[-1]]
        hero_rank = evaluate_7cards([Card(hero_combo[0]), Card(hero_combo[1]), *board_cards])
        villain_rank = evaluate_7cards([Card(villain_combo[0]), Card(villain_combo[1]), *board_cards])
        winner = 1 if hero_rank > villain_rank else (-1 if villain_rank > hero_rank else 0)
        if facing_bet:
            facing_bet_root(boards, winner, hero_combo, villain_combo)
        else:
            cfr(start_index, boards, winner, pot, 0.0, hero_combo, villain_combo, 1.0, 1.0)
        completed_iterations += 1

    def aggregate(player: str, street: str, actions: tuple[str, ...]) -> dict[str, float]:
        totals = {action: 0.0 for action in actions}
        for node in nodes.values():
            if node.player == player and node.street == street and node.actions == actions:
                for action in actions:
                    totals[action] += node.strategy_sum[action]
        total = sum(totals.values())
        if total <= 0:
            return {action: 1.0 / len(actions) for action in actions}
        return {action: totals[action] / total for action in actions}

    street_strategies = {street: aggregate("hero", street, HERO_ACTIONS) for street in STREETS}
    root_prefix = "D" if facing_bet else "H"
    root_actions = DEFENSE_ACTIONS if facing_bet else HERO_ACTIONS
    root_by_bucket = {
        key.split("|")[2]: node.average_strategy()
        for key, node in nodes.items()
        if key.startswith(f"{root_prefix}|") and node.street == start_street
    }
    root_values_by_bucket = {
        key.split("|")[2]: node.average_utilities()
        for key, node in nodes.items()
        if key.startswith(f"{root_prefix}|") and node.street == start_street
    }
    focus_bucket = hand_bucket(focus_combo, board) if focus_combo is not None else None
    focus_strategy = root_by_bucket.get(focus_bucket) if focus_bucket is not None else None
    focus_action_values = root_values_by_bucket.get(focus_bucket) if focus_bucket is not None else None
    line_strategy = focus_strategy or aggregate(
        "hero-defense" if facing_bet else "hero", start_street, root_actions
    )
    line_values = focus_action_values or {action: 0.0 for action in root_actions}
    ranked_lines = sorted(root_actions, key=lambda action: line_values[action], reverse=True)
    best_value = line_values[ranked_lines[0]]
    line_analysis = [
        {
            "rank": index + 1,
            "action": action,
            "ev": round(line_values[action], 3),
            "ev_loss": round(max(0.0, best_value - line_values[action]), 3),
            "weight": round(line_strategy[action], 3),
            "is_best": index == 0,
        }
        for index, action in enumerate(ranked_lines)
    ]
    principal_variation = [
        {"street": start_street, "action": max(line_strategy, key=line_strategy.get), "strategy": line_strategy}
    ]
    if principal_variation[0]["action"] != "fold":
        principal_variation.extend(
            {
                "street": street,
                "action": max(street_strategies[street], key=street_strategies[street].get),
                "strategy": street_strategies[street],
            }
            for street in STREETS[start_index + 1 :]
        )

    return {
        "method": "outcome-sampling-cfr",
        "abstraction": (
            "three hand buckets; fold/call/raise; fold/call/reraise all-in"
            if facing_bet
            else "three hand buckets; check/33%/75%; fold/call"
        ),
        "root_mode": "facing_bet" if facing_bet else "checked_to",
        "to_call": to_call,
        "raise_investment": resolved_min_raise if facing_bet else None,
        "raise_investments": raise_investments if facing_bet else None,
        "raise_is_all_in": facing_bet and resolved_min_raise >= effective_stack - 1e-9,
        "villain_response_actions": list(RERAISE_ACTIONS) if facing_bet else list(VILLAIN_ACTIONS),
        "all_in_response_actions": list(VILLAIN_ACTIONS),
        "iterations": completed_iterations,
        "start_street": start_street,
        "board": board,
        "flop": board[:3],
        "range_summary": {"hero_combos": len(hero_combos), "villain_combos": len(villain_combos)},
        "chance_nodes": {
            "sampled_turn_cards": len(sampled_turns),
            "sampled_river_cards": len(sampled_rivers),
        },
        "root_strategy": line_strategy,
        "root_strategy_by_bucket": root_by_bucket,
        "root_action_values_by_bucket": root_values_by_bucket,
        "focus_bucket": focus_bucket,
        "focus_strategy": focus_strategy,
        "focus_action_values": focus_action_values,
        "line_analysis": line_analysis,
        "street_strategies": street_strategies,
        "principal_variation": principal_variation,
        "information_sets": len(nodes),
    }


def solve_flop_subgame(
    hero_range: list[str],
    villain_range: list[str],
    flop: list[str],
    pot: float,
    effective_stack: float = 100.0,
    iterations: int = 1200,
    seed: int = 17,
    focus_combo: tuple[str, str] | None = None,
    to_call: float = 0.0,
    raise_investment: float | None = None,
    min_bet_investment: float | None = None,
) -> dict:
    if len(flop) != 3:
        raise ValueError("flop must contain exactly three cards")
    return solve_postflop_subgame(
        hero_range=hero_range,
        villain_range=villain_range,
        board=flop,
        pot=pot,
        effective_stack=effective_stack,
        iterations=iterations,
        seed=seed,
        focus_combo=focus_combo,
        to_call=to_call,
        raise_investment=raise_investment,
        min_bet_investment=min_bet_investment,
    )