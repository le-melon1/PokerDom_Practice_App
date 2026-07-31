"""Single place that wires up the sibling analysis project's card/equity
engine, so the rest of this app never has to think about the path hack."""

import sys
from pathlib import Path

_ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
if str(_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_ROOT))

from src.engine.cards import Card, Deck, evaluate_7cards  # noqa: E402

__all__ = ["Card", "Deck", "evaluate_7cards"]
