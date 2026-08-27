"""Per-Telegram-chat session state, mirroring backend/api.py's single global
`state` dict but keyed by chat_id instead of being one process-wide global --
see backend/api.py's own module docstring ("Single global table for now --
this is a local practice tool for one person, not a multi-tenant server")
for why that module's state shape can't just be reused directly for a bot
serving many independent chats.

Persistence follows the same idiom as api.py's _save_state()/_load_state()
(pickle the whole bundle to disk after every mutating action, atomic
tmp-file swap), just one file per chat_id instead of one shared file --
avoids a giant shared pickle being rewritten on every user's every action,
and keeps one corrupt file from taking down every user's session.
"""

import pickle
from dataclasses import dataclass, field
from pathlib import Path

from backend.dossier import TableDossier
from backend.engine.hand import Hand
from backend.engine.table import Table
from backend.hand_history import HandHistoryStore, HeroDecision
from backend.sessions.live_dynamics import TableTurnover

SESSIONS_DIR = Path(__file__).resolve().parent / "data" / "sessions"

DEFAULT_SETTINGS = {
    "hints_enabled": True,
    "allowed_archetypes": None,
    "player_profile_ids": None,
    "starting_stack": 200.0,
    "max_seats": 6,
    # drill mode (2026-08-26): names of abc_bot.py flags (see drills.py's
    # DRILL_SPECS) the user is currently drilling. Empty = normal play.
    "drill_flags": [],
}


@dataclass
class BotSession:
    chat_id: int
    hero_seat: int = 1
    table: Table | None = None
    hand: Hand | None = None
    dossier: TableDossier | None = None
    turnover: TableTurnover | None = None
    starting_stack: float = 200.0
    hand_history: HandHistoryStore | None = None
    hand_number: int = 0
    hero_decisions: list[HeroDecision] = field(default_factory=list)
    # Telegram-specific: one dict per hero action THIS hand (street/action/
    # amount/grade/verdict/abc_action/abc_amount) -- powers the full
    # per-street end-of-hand review, not just the last action's feedback.
    street_decisions: list[dict] = field(default_factory=list)
    settings: dict = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    # Telegram-specific: the chat message currently showing the table, so
    # later updates can edit it in place instead of spamming new messages.
    table_message_id: int | None = None


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[int, BotSession] = {}

    def _path(self, chat_id: int) -> Path:
        return SESSIONS_DIR / f"{chat_id}.pkl"

    def get(self, chat_id: int) -> BotSession | None:
        if chat_id in self._sessions:
            return self._sessions[chat_id]
        loaded = self._load(chat_id)
        if loaded is not None:
            self._sessions[chat_id] = loaded
        return self._sessions.get(chat_id)

    def get_or_create(self, chat_id: int) -> tuple[BotSession, bool]:
        """Returns (session, created) -- created=True means this chat_id had
        no existing session (in memory or on disk) and a fresh one was made."""
        existing = self.get(chat_id)
        if existing is not None:
            return existing, False
        session = BotSession(chat_id=chat_id)
        self._sessions[chat_id] = session
        return session, True

    def save(self, session: BotSession) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = self._path(session.chat_id)
        tmp_path = path.with_suffix(".pkl.tmp")
        with open(tmp_path, "wb") as fh:
            pickle.dump(session, fh)
        tmp_path.replace(path)  # atomic swap, same rationale as api.py's _save_state()

    def _load(self, chat_id: int) -> BotSession | None:
        path = self._path(chat_id)
        if not path.exists():
            return None
        try:
            with open(path, "rb") as fh:
                return pickle.load(fh)
        except Exception:
            return None  # corrupt/incompatible save (e.g. after an engine code change) -- start fresh
