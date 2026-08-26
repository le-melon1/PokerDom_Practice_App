"""Pure functions: Hand/Table/session -> Telegram message text +
InlineKeyboardMarkup. No poker logic here -- everything is read from what
game.py / the engine already computed."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.telegram_bot import drills
from backend.telegram_bot.session import BotSession

SUIT_EMOJI = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}
STREET_RU = {"preflop": "префлоп", "flop": "флоп", "turn": "тёрн", "river": "ривер"}


def _card(card: str) -> str:
    if card == "??":
        return "🂠"
    rank, suit = card[0], card[1]
    return f"{rank}{SUIT_EMOJI.get(suit, suit)}"


def _cards(cards: list[str]) -> str:
    if not cards:
        return "-"
    return " ".join(_card(c) for c in cards)


def render_table_text(session: BotSession, trainer_feedback: dict | None = None) -> str:
    table = session.table
    hand = session.hand
    lines = []

    drill_flags = session.settings.get("drill_flags") or []
    if drill_flags:
        labels = [drills.FLAG_LABEL_RU.get(f, f) for f in drill_flags]
        lines.append(f"🎯 Тренировка: {', '.join(labels)}")
        lines.append("")

    if hand is None:
        lines.append("Стол готов. /newhand -- раздать первую руку.")
        return "\n".join(lines)

    street = STREET_RU.get(hand.street, hand.street)
    pot = sum(p.total_contributed for p in hand.players.values())
    lines.append(f"<b>{street}</b>   Банк: {pot:.1f}bb")
    lines.append(f"Борд: {_cards(hand.board)}")
    lines.append("")

    for seat in sorted(table.players):
        p = table.players[seat]
        marker = "👉 " if hand.current_actor() == seat else "   "
        tag = " (Вы)" if seat == session.hero_seat else ""
        state_bits = []
        if p.folded:
            state_bits.append("fold")
        if p.all_in:
            state_bits.append("all-in")
        if p.sitting_out:
            state_bits.append("вне игры")
        state = f" [{', '.join(state_bits)}]" if state_bits else ""
        cards = _cards(_visible_hole_cards(session, seat, p))
        lines.append(f"{marker}{p.name}{tag}: {p.stack:.1f}bb (ставка {p.street_contributed:.1f}) {cards}{state}")

    if hand.finished and hand.result is not None:
        lines.append("")
        lines.append("Раздача завершена. /newhand -- следующая.")

    if trainer_feedback is not None:
        lines.append("")
        lines.append(f"📊 {trainer_feedback['verdict']}")

    return "\n".join(lines)


def _visible_hole_cards(session: BotSession, seat: int, player) -> list[str]:
    hand = session.hand
    if seat == session.hero_seat:
        return player.hole_cards
    if hand is None:
        return []
    real_showdown = hand.finished and hand.result is not None and len(hand.result.winners_by_pot) > 0
    if real_showdown and player.in_hand:
        return player.hole_cards
    if not hand.finished and player.in_hand:
        return ["??", "??"]
    return []


def build_action_keyboard(session: BotSession) -> InlineKeyboardMarkup | None:
    hand = session.hand
    if hand is None or hand.finished or hand.current_actor() != session.hero_seat:
        return None
    legal = hand.legal_actions(session.hero_seat)

    row = [InlineKeyboardButton("Фолд", callback_data="act:fold")]
    if legal["can_check"]:
        row.append(InlineKeyboardButton("Чек", callback_data="act:check"))
    else:
        row.append(InlineKeyboardButton(f"Колл {legal['call_amount']:.1f}", callback_data="act:call"))
    if legal["max_raise_to"] > legal["min_raise_to"] - 1e-9:
        row.append(InlineKeyboardButton("Рейз/Бет", callback_data="act:raise_menu"))

    rows = [row]
    if session.settings.get("hints_enabled"):
        rows.append([InlineKeyboardButton("💡 Подсказка", callback_data="hint:show")])
    return InlineKeyboardMarkup(rows)


def compute_raise_presets(session: BotSession) -> dict[str, float]:
    """Preset raise-to (absolute) amounts, sized relative to the pot AFTER a
    call -- standard poker-room bet-sizing convention. Clamped to the legal
    [min_raise_to, max_raise_to] range."""
    hand = session.hand
    legal = hand.legal_actions(session.hero_seat)
    player = hand.players[session.hero_seat]
    pot = sum(p.total_contributed for p in hand.players.values())
    pot_after_call = pot + legal["call_amount"]
    base = player.street_contributed + legal["call_amount"]

    min_to = legal["min_raise_to"]
    max_to = legal["max_raise_to"]

    def clamp(x: float) -> float:
        return max(min_to, min(x, max_to))

    return {
        "1/3 пота": clamp(base + 0.33 * pot_after_call),
        "1/2 пота": clamp(base + 0.5 * pot_after_call),
        "Пот": clamp(base + 1.0 * pot_after_call),
        "Ва-банк": max_to,
    }


def build_raise_size_keyboard(session: BotSession) -> InlineKeyboardMarkup:
    presets = compute_raise_presets(session)
    row = [
        InlineKeyboardButton(f"{label} ({amount:.1f})", callback_data=f"raise:{label}")
        for label, amount in presets.items()
    ]
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("« Назад", callback_data="act:back")]])


ACTION_RU = {"fold": "фолд", "check": "чек", "call": "колл", "raise": "рейз/бет", "bet": "рейз/бет"}
ARCHETYPE_RU = {
    "Nit": "Нит",
    "TAG": "TAG",
    "LAG": "LAG",
    "Loose-passive": "Лузи-пассив",
    "Station": "Колл-стэйшн",
    "Maniac": "Маньяк",
}
FREQ_TIER_RU = {"rare": "редко", "normal": "средне", "often": "часто"}
TILT_TIER_RU = {"none": "спокоен", "acute": "тильт (остро)", "fading": "тильт (спадает)", "residual": "тильт (следы)"}


def render_hint_text(hint: dict) -> str:
    """Renders game.compute_abc_strategy_hint()'s output -- the ABC bot's
    own recommendation, fed the same live opponent reads a seated bot's
    decisions use, NOT an equity/CFR panel."""
    action_ru = ACTION_RU.get(hint["action"], hint["action"])
    amount = hint["amount"]
    lines = ["<b>💡 Подсказка (наша стратегия)</b>"]
    rec_line = f"Рекомендация: <b>{action_ru}</b>"
    if amount is not None:
        rec_line += f" до {amount:.1f}bb"
    lines.append(rec_line)

    opponents = hint["opponents"]
    if opponents:
        lines.append("")
        lines.append("Прочитано по сопернику(ам):")
        for opp in opponents:
            archetype = ARCHETYPE_RU.get(opp["archetype"], opp["archetype"])
            freq = FREQ_TIER_RU.get(opp["freq_tier"], opp["freq_tier"])
            tilt = TILT_TIER_RU.get(opp["tilt_tier"], opp["tilt_tier"])
            tilt_part = f", {tilt}" if opp["tilt_tier"] != "none" else ""
            lines.append(f"  {opp['name']}: {archetype}, играет {freq}{tilt_part}")
    return "\n".join(lines)


def build_settings_keyboard(session: BotSession) -> InlineKeyboardMarkup:
    hints_label = "Подсказки: вкл ✅" if session.settings.get("hints_enabled") else "Подсказки: выкл"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(hints_label, callback_data="settings:hints_toggle")],
            [InlineKeyboardButton("🔄 Сбросить стол", callback_data="settings:reset")],
        ]
    )


# ---- drill mode menu: /drills -> Префлоп/Постфлоп -> category -> flags ----


def build_drill_root_keyboard(session: BotSession) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("Префлоп", callback_data="drill:stage:preflop")],
        [InlineKeyboardButton("Постфлоп", callback_data="drill:stage:postflop")],
    ]
    if session.settings.get("drill_flags"):
        rows.append([InlineKeyboardButton("🔙 Обычная игра (сбросить тренировку)", callback_data="drill:exit")])
    return InlineKeyboardMarkup(rows)


def build_drill_category_keyboard(stage: str) -> InlineKeyboardMarkup:
    flag_list = drills.PREFLOP_FLAGS if stage == "preflop" else drills.POSTFLOP_FLAGS
    categories = sorted({drills.FLAG_CATEGORY[f] for f in flag_list})
    rows = [
        [InlineKeyboardButton(drills.CATEGORY_LABEL_RU.get(cat, cat), callback_data=f"drill:cat:{cat}")]
        for cat in categories
    ]
    rows.append([InlineKeyboardButton("« Назад", callback_data="drill:root")])
    return InlineKeyboardMarkup(rows)


def build_drill_flag_keyboard(session: BotSession, category: str) -> InlineKeyboardMarkup:
    selected = set(session.settings.get("drill_flags") or [])
    flags = sorted(f for f, c in drills.FLAG_CATEGORY.items() if c == category)
    rows = []
    for flag in flags:
        mark = "✅ " if flag in selected else "⬜ "
        label = mark + drills.FLAG_LABEL_RU.get(flag, flag)
        rows.append([InlineKeyboardButton(label, callback_data=f"drill:toggle:{flag}")])
    stage = "preflop" if category.startswith("preflop") else "postflop"
    rows.append([InlineKeyboardButton("« Категории", callback_data=f"drill:stage:{stage}")])
    if selected:
        rows.append([InlineKeyboardButton("🎯 Начать тренировку", callback_data="drill:start")])
    return InlineKeyboardMarkup(rows)


def render_drill_intro_text() -> str:
    return (
        "<b>Тренировка по правилам</b>\n"
        "Выбери одно или несколько правил стратегии, чтобы стол специально "
        "подстраивался под нужный сценарий (архетипы соперников, форсированные "
        "карты/действия) — сценарий будет встречаться почти каждую раздачу, "
        "а не раз в тысячу."
    )
