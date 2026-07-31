from __future__ import annotations

import math


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    max_value = max(values)
    spread = max_value - min(values)
    temperature = max(0.5, spread * 0.35)
    exponentials = [math.exp((value - max_value) / temperature) for value in values]
    total = sum(exponentials)
    return [value / total for value in exponentials]


def solve_gto_wizard_like_strategy(
    equity: float,
    pot: float,
    to_call: float,
    legal_actions: dict | None = None,
    raise_sizes: list[float] | None = None,
) -> dict:
    """Create a richer solver-like recommendation for a single street.

    The output is intentionally closer to a real GTO-trainer experience than
    the earlier toy matrix solver: it evaluates multiple sizing candidates,
    ranks them by EV, and returns a softmax-style action mix so the UI can
    present a more realistic "solver" panel.
    """
    legal_actions = legal_actions or {}
    min_raise_to = legal_actions.get("min_raise_to", 0.0)
    max_raise_to = legal_actions.get("max_raise_to", min_raise_to)
    can_check = bool(legal_actions.get("can_check", False))
    can_call = bool(legal_actions.get("can_call", False))

    actions: list[dict] = []
    if can_call:
        actions.append({"action": "fold", "amount": None, "label": "Фолд"})
    if can_check:
        actions.append({"action": "check", "amount": None, "label": "Чек"})
    if can_call:
        actions.append({"action": "call", "amount": to_call, "label": "Колл"})

    default_sizes = [min_raise_to, min_raise_to + max(0.0, pot * 0.5), min_raise_to + pot, max_raise_to]
    if raise_sizes:
        default_sizes = raise_sizes
    seen = set()
    for size in default_sizes:
        if size is None:
            continue
        size = float(size)
        key = round(size, 4)
        if key in seen:
            continue
        seen.add(key)
        if size > 0 and size >= min_raise_to - 1e-9:
            actions.append({"action": "raise", "amount": size, "label": f"Рейз {size:.2f}bb"})

    if not actions:
        return {
            "recommended_action": "fold",
            "recommended_amount": None,
            "action_weights": {"fold": 1.0},
            "actions": [{"action": "fold", "amount": None, "label": "Фолд"}],
            "tree": [],
        }

    evs: list[float] = []
    for entry in actions:
        action = entry["action"]
        amount = entry["amount"]
        if action == "check":
            ev = pot * equity * 0.5
        elif action == "fold":
            ev = 0.0
        elif action == "call":
            ev = (pot + max(0.0, to_call)) * equity - max(0.0, to_call)
        elif action == "raise":
            bet = amount or 0.0
            ev = (pot + bet) * equity - bet
        else:
            ev = 0.0
        evs.append(ev)

    weights = _normalize(evs)
    best_idx = max(range(len(actions)), key=lambda idx: evs[idx])
    recommended = actions[best_idx]

    action_weights = {
        entry["action"] + (f":{entry['amount']:.2f}" if entry.get("amount") is not None and entry["action"] == "raise" else ""): weight
        for entry, weight in zip(actions, weights)
    }

    tree = [
        {
            "node": "hero",
            "street": "single-street",
            "recommended": recommended["action"],
            "weights": action_weights,
        }
    ]

    line_analysis = []
    ranked = sorted(
        [
            {
                "action": entry["action"],
                "amount": entry["amount"],
                "ev": evs[idx],
                "weight": weights[idx],
            }
            for idx, entry in enumerate(actions)
        ],
        key=lambda item: item["ev"],
        reverse=True,
    )
    best_ev = ranked[0]["ev"]
    near_mix_threshold = max(0.05, pot * 0.01)
    for idx, item in enumerate(ranked[:3]):
        ev_loss = max(0.0, best_ev - item["ev"])
        if idx == 0:
            category = "best"
            explanation = "Highest estimated EV in the current node."
        elif ev_loss <= near_mix_threshold:
            category = "near-mix"
            explanation = f"Only {ev_loss:.3f}bb below the best line; a viable mixed alternative."
        else:
            category = "alternative"
            explanation = f"Costs {ev_loss:.3f}bb versus the best line in this model."
        line_analysis.append(
            {
                "rank": idx + 1,
                "action": item["action"],
                "amount": item["amount"],
                "ev": round(item["ev"], 3),
                "ev_loss": round(ev_loss, 3),
                "weight": round(item["weight"], 3),
                "label": f"{item['action']}" + (f" {item['amount']:.2f}bb" if item["amount"] is not None else ""),
                "category": category,
                "is_best": idx == 0,
                "explanation": explanation,
            }
        )

    return {
        "recommended_action": recommended["action"],
        "recommended_amount": recommended["amount"],
        "action_weights": action_weights,
        "actions": actions,
        "ranked_actions": ranked,
        "tree": tree,
        "line_analysis": line_analysis,
    }
