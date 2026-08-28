"""Persistent log of hand disputes the user flags via the post-hand
"⚠️ Оспорить совет" button. Per explicit user request: pick which street's
recommendation you disagree with, optionally add a comment, and the
decision gets appended here for later manual review ("потом мы это
проверим") -- this module only records, it doesn't judge or act on
anything itself.

One JSONL file (append-only, one record per line) rather than a real
database -- this bot's whole persistence layer is already per-chat pickle
files (see session.py's own docstring for why), a JSONL log fits the same
"simple enough for a local single-operator tool" spirit and is trivial to
read back for review (one json.loads per line, no schema migration)."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

DISPUTES_PATH = Path(__file__).resolve().parent / "data" / "disputes.jsonl"


@dataclass
class Dispute:
    chat_id: int
    hand_number: int
    street: str
    hero_action: str
    hero_amount: float | None
    abc_action: str
    abc_amount: float | None
    comment: str
    created_at: str


def record_dispute(dispute: Dispute) -> None:
    DISPUTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DISPUTES_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(dispute), ensure_ascii=False) + "\n")


def load_disputes() -> list[dict]:
    """For the later review pass ("потом мы это проверим") -- not called
    anywhere in the bot itself yet."""
    if not DISPUTES_PATH.exists():
        return []
    with open(DISPUTES_PATH, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
