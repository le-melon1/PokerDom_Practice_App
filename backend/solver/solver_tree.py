from __future__ import annotations


STREETS = ("preflop", "flop", "turn", "river")


def _next_street(street: str) -> str | None:
    try:
        index = STREETS.index(street)
    except ValueError:
        return None
    return STREETS[index + 1] if index + 1 < len(STREETS) else None


def _bet_ev(pot: float, equity: float, amount: float) -> tuple[float, float]:
    fold_probability = amount / (pot + amount) if pot + amount > 0 else 0.0
    called_ev = equity * (pot + 2 * amount) - amount
    ev = fold_probability * pot + (1 - fold_probability) * called_ev
    return ev, fold_probability


def _project_future_node(street: str, pot: float, equity: float) -> dict:
    branches = [
        {
            "action": "check",
            "amount": None,
            "ev": round(equity * pot, 3),
            "description": "realize range equity",
        }
    ]
    for fraction in (0.33, 0.75):
        amount = pot * fraction
        ev, fold_probability = _bet_ev(pot, equity, amount)
        branches.append(
            {
                "action": "bet",
                "amount": round(amount, 2),
                "pot_fraction": fraction,
                "ev": round(ev, 3),
                "fold_probability": round(fold_probability, 3),
                "description": f"{fraction:.0%} pot using minimum-defense-frequency response",
            }
        )

    next_street = _next_street(street)
    if next_street is not None:
        best_branch = max(branches, key=lambda item: item["ev"])
        projected_pot = pot if best_branch["action"] == "check" else pot + 2 * best_branch["amount"]
        best_branch["next_node"] = _project_future_node(next_street, projected_pot, equity)

    return {
        "node": "future-street",
        "street": street,
        "pot": round(pot, 2),
        "equity": round(equity, 4),
        "summary": "range-equity projection; runout information not yet observed",
        "branches": branches,
    }


def _principal_variation(street: str, branches: list[dict]) -> list[dict]:
    if not branches:
        return []
    best_branch = max(branches, key=lambda item: item["ev"])
    line = [
        {
            "street": street,
            "action": best_branch["action"],
            "amount": best_branch.get("amount"),
            "ev": best_branch["ev"],
        }
    ]
    next_node = best_branch.get("next_node")
    if next_node:
        line.extend(_principal_variation(next_node["street"], next_node["branches"]))
    return line


def build_solver_tree(street: str, pot: float, to_call: float, equity: float, actions: list[dict]) -> list[dict]:
    """Build a bounded multi-street solver-style projection for the UI.

    Future nodes use minimum-defense-frequency responses for standard bet
    sizes. Equity remains constant in expectation until a real runout is
    observed; this is a projection, not a full card-by-card game-tree solve.
    """
    branches = []
    raise_amounts = [entry.get("amount") for entry in actions if entry["action"] == "raise" and entry.get("amount")]
    all_in_amount = max(raise_amounts) if raise_amounts else None
    for entry in actions:
        action = entry["action"]
        amount = entry.get("amount")
        if action == "check":
            ev = pot * equity * 0.5
            desc = "pot control"
        elif action == "call":
            ev = (pot + max(0.0, to_call)) * equity - max(0.0, to_call)
            desc = "continue with equity"
        elif action == "raise":
            bet = amount or 0.0
            ev = (pot + bet) * equity - bet
            desc = f"value + fold equity at {amount:.2f}bb"
        else:
            ev = 0.0
            desc = "baseline"
        branch = {
            "action": action,
            "amount": amount,
            "ev": round(ev, 3),
            "description": desc,
        }
        next_street = _next_street(street)
        is_all_in = action == "raise" and amount == all_in_amount
        if action != "fold" and not is_all_in and next_street is not None:
            if action == "check":
                projected_pot = pot
            elif action == "call":
                projected_pot = pot + max(0.0, to_call)
            else:
                projected_pot = pot + 2 * (amount or 0.0)
            branch["next_node"] = _project_future_node(next_street, projected_pot, equity)
        branches.append(branch)

    return [{
        "node": "root",
        "street": street,
        "summary": "current decision with projected future streets",
        "branches": branches,
        "principal_variation": _principal_variation(street, branches),
    }]
