from __future__ import annotations


def _regret_matching(regrets: list[float], actions: list[str]) -> dict[str, float]:
    positive = [max(0.0, value) for value in regrets]
    total = sum(positive)
    if total <= 0:
        weight = 1.0 / len(actions)
        return {action: weight for action in actions}
    return {action: positive[idx] / total for idx, action in enumerate(actions)}


def solve_cfr_equilibrium(
    equity: float,
    pot: float,
    to_call: float,
    raise_amount: float | None = None,
    iterations: int = 2000,
) -> dict:
    """Solve a small one-street poker game with CFR.

    The game is intentionally compact: hero chooses among fold/call/raise,
    villain responds with fold/call if the hero checks or calls, and the
    terminal values use a simplified equity-based utility model. This is still
    CFR in spirit: regret updates, mixed strategy, and average strategy
    extraction, but bounded to a single decision layer to remain fast and
    reliable for a local app.
    """
    hero_actions = ["fold", "call", "raise"]
    villain_actions = ["fold", "call"]
    resolved_raise_amount = raise_amount if raise_amount is not None else max(to_call, pot)

    hero_regrets = [0.0, 0.0, 0.0]
    villain_regrets = [0.0, 0.0]
    hero_strategy_sum = [0.0, 0.0, 0.0]
    villain_strategy_sum = [0.0, 0.0]

    def terminal_value(hero_action: str, villain_action: str) -> float:
        if hero_action == "fold":
            return 0.0
        if villain_action == "fold":
            return pot

        amount = resolved_raise_amount if hero_action == "raise" else to_call
        effective_pot = pot + amount * 2
        return effective_pot * (2 * equity - 1) - amount

    for _ in range(iterations):
        hero_strategy = _regret_matching(hero_regrets, hero_actions)
        villain_strategy = _regret_matching(villain_regrets, villain_actions)

        for idx, action in enumerate(hero_actions):
            hero_strategy_sum[idx] += hero_strategy[action]

        for idx, action in enumerate(villain_actions):
            villain_strategy_sum[idx] += villain_strategy[action]

        action_utils = {}
        for hero_action in hero_actions:
            if hero_action == "fold":
                action_utils[hero_action] = 0.0
            else:
                node_value = 0.0
                for villain_action in villain_actions:
                    if villain_action == "fold":
                        util = terminal_value(hero_action, villain_action)
                    else:
                        util = terminal_value(hero_action, villain_action)
                    node_value += villain_strategy[villain_action] * util
                action_utils[hero_action] = node_value

        hero_node_value = sum(hero_strategy[action] * action_utils[action] for action in hero_actions)
        for idx, action in enumerate(hero_actions):
            hero_regrets[idx] += action_utils[action] - hero_node_value

        villain_action_utils = {}
        for villain_action in villain_actions:
            node_value = 0.0
            for hero_action in hero_actions:
                if hero_action == "fold":
                    util = terminal_value(hero_action, villain_action)
                else:
                    util = terminal_value(hero_action, villain_action)
                node_value += hero_strategy[hero_action] * util
            villain_action_utils[villain_action] = node_value

        villain_node_value = sum(villain_strategy[action] * villain_action_utils[action] for action in villain_actions)
        for idx, action in enumerate(villain_actions):
            villain_regrets[idx] += villain_action_utils[action] - villain_node_value

    def avg_strategy(values: list[float], actions: list[str]) -> dict[str, float]:
        total = sum(values)
        if total <= 0:
            uniform = 1.0 / len(actions)
            return {action: uniform for action in actions}
        return {action: values[idx] / total for idx, action in enumerate(actions)}

    hero_policy = avg_strategy(hero_strategy_sum, hero_actions)
    villain_policy = avg_strategy(villain_strategy_sum, villain_actions)

    return {
        "hero_strategy": hero_policy,
        "villain_strategy": villain_policy,
        "hero_value": sum(hero_policy[action] * terminal_value(action, "call") for action in hero_actions),
        "pot": pot,
        "to_call": to_call,
        "raise_amount": resolved_raise_amount,
        "equity": equity,
        "method": "cfr",
    }
