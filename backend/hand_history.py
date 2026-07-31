"""Hand history + post-hand decision grading ("GTO Wizard-style": compare what
the hero actually did against what the live EV engine said *at the moment of
that decision*, then show the verdict after the hand is over).

Deliberately scoped, not a full solver comparison:
    - Grading compares the chosen action (and nearest available raise sizing)
        against the bounded solver action list at the moment of the decision.
  - The EV snapshot used for grading is always the "auto" (dossier-blended)
    read, regardless of what the user had selected in the live panel's
    archetype dropdown -- grading needs one consistent, objective baseline,
    not whatever hypothesis the user happened to be testing at the time.
"""

from dataclasses import dataclass, field
from typing import Any

from backend.engine.hand import Hand
from backend.ev.live_ev import LiveEVResult

BOARD_LEN_BY_STREET = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}


@dataclass
class HeroDecision:
    street: str
    pot_before: float
    to_call: float
    action: str
    amount: float | None
    equity_vs_range: float | None
    ev_call: float | None
    breakeven_equity: float | None
    confidence: float
    solver_action: str | None = None
    solver_amount: float | None = None
    chosen_ev: float | None = None
    solver_best_ev: float | None = None
    solver_ev_loss: float | None = None

    @property
    def trainer_grade(self) -> str:
        loss = getattr(self, "solver_ev_loss", None)
        if loss is None:
            return "ungraded"
        if loss <= 0.05:
            return "optimal"
        if loss <= 0.5:
            return "inaccuracy"
        if loss <= 2.0:
            return "mistake"
        return "blunder"

    @property
    def verdict(self) -> str:
        loss = getattr(self, "solver_ev_loss", None)
        if loss is not None:
            labels = {
                "optimal": "оптимально",
                "inaccuracy": "неточность",
                "mistake": "ошибка",
                "blunder": "грубая ошибка",
            }
            grade = self.trainer_grade
            if grade == "optimal":
                return f"{labels[grade]}: потеря {loss:.2f}bb"
            solver_action = getattr(self, "solver_action", None) or "другая линия"
            return f"{labels[grade]}: потеря {loss:.2f}bb; solver предпочитает {solver_action}"
        if self.action == "fold":
            if self.to_call <= 0:
                return "ошибка: сфолдили, хотя чек был бесплатным"
            if self.ev_call is None:
                return "не оценивается"
            if self.ev_call > 0:
                return f"-EV фолд: отдали ~{self.ev_call:.2f}bb (колл был +EV)"
            return "ок: фолд был верным (колл -EV)"
        if self.action == "call":
            if self.ev_call is None:
                return "не оценивается"
            if self.ev_call < 0:
                return f"-EV колл: {self.ev_call:.2f}bb"
            return f"+EV колл: {self.ev_call:.2f}bb"
        if self.action == "check":
            return "нейтрально (бесплатно)"
        return "не оценивается (сайзинг бет/рейза модель не считает)"

    @property
    def is_mistake(self) -> bool:
        if getattr(self, "solver_ev_loss", None) is not None:
            return self.trainer_grade != "optimal"
        return self.verdict.startswith("-EV") or self.verdict.startswith("ошибка")


def grade_decision(
    street: str,
    to_call: float,
    action: str,
    amount: float | None,
    ev: LiveEVResult,
    recommendation: Any | None = None,
) -> HeroDecision:
    chosen = None
    if recommendation is not None:
        matching = [item for item in recommendation.action_evs if item.action == action]
        if matching:
            if action in {"raise", "bet"} and amount is not None:
                chosen = min(matching, key=lambda item: abs((item.amount or 0.0) - amount))
            else:
                chosen = matching[0]
    best_ev = recommendation.best_ev if recommendation is not None else None
    chosen_ev = chosen.ev if chosen is not None else None
    ev_loss = None
    if best_ev is not None and chosen_ev is not None:
        ev_loss = max(0.0, best_ev - chosen_ev)

    return HeroDecision(
        street=street,
        pot_before=ev.pot_before,
        to_call=to_call,
        action=action,
        amount=amount,
        equity_vs_range=ev.equity_vs_range,
        ev_call=ev.ev_call,
        breakeven_equity=ev.breakeven_equity,
        confidence=ev.confidence,
        solver_action=recommendation.recommended_action if recommendation is not None else None,
        solver_amount=recommendation.recommended_amount if recommendation is not None else None,
        chosen_ev=chosen_ev,
        solver_best_ev=best_ev,
        solver_ev_loss=ev_loss,
    )


@dataclass
class HandHistoryEntry:
    hand_number: int
    hero_seat: int
    hero_cards: list[str]
    final_board: list[str]
    action_log: list[dict]
    payouts: dict[int, float]
    rake: float
    hero_net: float
    decisions: list[HeroDecision] = field(default_factory=list)

    def board_at_street(self, street: str) -> list[str]:
        return self.final_board[: BOARD_LEN_BY_STREET.get(street, len(self.final_board))]

    @property
    def mistake_count(self) -> int:
        return sum(1 for d in self.decisions if d.is_mistake)


class HandHistoryStore:
    def __init__(self, max_entries: int = 200):
        self.entries: list[HandHistoryEntry] = []
        self.max_entries = max_entries

    def record(self, hand: Hand, hand_number: int, hero_seat: int, decisions: list[HeroDecision]) -> None:
        hero = hand.players[hero_seat]
        payouts = hand.result.payouts if hand.result else {}
        rake = hand.result.rake if hand.result else 0.0
        invested = hero.total_contributed
        hero_net = payouts.get(hero_seat, 0.0) - invested

        entry = HandHistoryEntry(
            hand_number=hand_number,
            hero_seat=hero_seat,
            hero_cards=list(hero.hole_cards),
            final_board=list(hand.board),
            action_log=[
                {"seat": a.seat, "street": a.street, "action": a.action, "amount": a.amount} for a in hand.actions
            ],
            payouts=dict(payouts),
            rake=rake,
            hero_net=hero_net,
            decisions=decisions,
        )
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries.pop(0)

    def list_summaries(self, limit: int = 50) -> list[dict]:
        return [
            {
                "hand_number": e.hand_number,
                "hero_net": round(e.hero_net, 2),
                "rake": round(e.rake, 2),
                "mistake_count": e.mistake_count,
                "final_board": e.final_board,
            }
            for e in self.entries[-limit:][::-1]
        ]

    def get(self, hand_number: int) -> HandHistoryEntry | None:
        for e in self.entries:
            if e.hand_number == hand_number:
                return e
        return None
