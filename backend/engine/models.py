"""Core data holders for the game engine."""

from dataclasses import dataclass, field


@dataclass
class Player:
    seat: int
    name: str
    stack: float
    hole_cards: list[str] = field(default_factory=list)
    folded: bool = False
    all_in: bool = False
    sitting_out: bool = False
    street_contributed: float = 0.0
    total_contributed: float = 0.0

    @property
    def can_act(self) -> bool:
        return not self.folded and not self.all_in and not self.sitting_out and self.stack > 0

    @property
    def in_hand(self) -> bool:
        return not self.folded and not self.sitting_out


@dataclass
class ActionRecord:
    street: str
    seat: int
    action: str  # folds, checks, calls, bets, raises
    amount: float = 0.0
