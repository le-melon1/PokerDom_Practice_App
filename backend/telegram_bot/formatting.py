"""Pure functions: Hand/Table/session -> Telegram message text +
InlineKeyboardMarkup. No poker logic here -- everything is read from what
game.py / the engine already computed."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from backend.bots import abc_bot
from backend.bots.behavior_clone import _n_raises_this_street, _seat_position
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
        position = _seat_position(hand, seat)
        state_bits = []
        if p.folded:
            state_bits.append("fold")
        if p.all_in:
            state_bits.append("all-in")
        if p.sitting_out:
            state_bits.append("вне игры")
        state = f" [{', '.join(state_bits)}]" if state_bits else ""
        cards = _cards(_visible_hole_cards(session, seat, p))
        lines.append(
            f"{marker}[{position}] {p.name}{tag}: {p.stack:.1f}bb (ставка {p.street_contributed:.1f}) {cards}{state}"
        )

    if hand.finished and hand.result is not None:
        lines.append("")
        lines.append("Раздача завершена. /newhand -- следующая.")
        review = render_hand_review(session)
        if review:
            lines.append("")
            lines.append(review)
    elif trainer_feedback is not None:
        lines.append("")
        lines.append(f"📊 {trainer_feedback['verdict']}")

    return "\n".join(lines)


def render_hand_review(session: BotSession) -> str:
    """Full per-street breakdown of EVERY hero decision this hand (not just
    the last one) -- what hero did, whether that matched what optimal play
    was worth (✅/❌, from the existing solver-based EV-loss grade), and
    what the ABC strategy (choose_abc_action) itself recommended at that
    exact point. We don't attribute this to one specific abc_bot.py flag by
    name -- reliably pinpointing which of the ~30 interacting rules drove
    a single decision would need much deeper instrumentation than exists
    today; this shows the strategy's actual recommendation instead, which
    is the honest thing we can compute."""
    decisions = session.street_decisions
    if not decisions:
        return ""
    lines = ["<b>Разбор по улицам:</b>"]
    for d in decisions:
        street_ru = STREET_RU.get(d["street"], d["street"])
        icon = "✅" if d["grade"] == "optimal" else "❌"
        action_ru = ACTION_RU.get(d["action"], d["action"])
        action_part = f"{action_ru}" + (f" {d['amount']:.1f}bb" if d["amount"] else "")
        abc_action_ru = ACTION_RU.get(d["abc_action"], d["abc_action"])
        abc_part = f"{abc_action_ru}" + (f" {d['abc_amount']:.1f}bb" if d["abc_amount"] else "")
        lines.append(f"{icon} <b>{street_ru}</b>: вы — {action_part}; стратегия — {abc_part}")
        lines.append(f"   {d['verdict']}")
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
    """Postflop preset raise-to (absolute) amounts, sized relative to the
    pot AFTER a call. This genuinely matches how abc_bot.py sizes postflop
    bets (STANDARD_SIZING_POT_FRACTION=0.50, BIG_VALUE_SIZING_POT_FRACTION=
    0.75, overbets=1.5x pot) -- pot-fraction sizing is the real convention
    postflop, unlike preflop (see compute_preflop_raise_presets)."""
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


def compute_preflop_raise_presets(session: BotSession) -> dict[str, float]:
    """Preflop preset raise-to amounts, using the ACTUAL sizing formulas
    abc_bot.py's own rules compute (2.5bb open, 5.5bb+1.5bb/limper iso,
    position-scaled 3-bet multiplier, shove) -- not generic pot fractions.
    Per explicit user request: only sizes that exist in the real rules,
    not arbitrary tiers. Real preflop sizing is close to ONE formula-
    driven number per spot (not several tiers the way postflop's pot-
    fraction sizing naturally offers), so this returns just that one
    context-appropriate preset plus the always-available all-in."""
    hand = session.hand
    seat = session.hero_seat
    legal = hand.legal_actions(seat)
    position = _seat_position(hand, seat)
    min_to, max_to = legal["min_raise_to"], legal["max_raise_to"]

    def clamp(x: float) -> float:
        return max(min_to, min(x, max_to))

    presets: dict[str, float] = {}
    n_raises = _n_raises_this_street(hand)

    if n_raises == 0:
        n_limpers = abc_bot._n_limpers_preflop(hand)
        if abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS and n_limpers >= 1:
            bb = abc_bot.TIGHT_ISO_BASE_SIZING_BB + abc_bot.TIGHT_ISO_SIZING_PER_LIMPER_BB * n_limpers
            amount = clamp(hand.big_blind * bb)
            presets[f"Изо {bb:.1f}bb"] = amount
        else:
            bb = abc_bot.OPEN_SIZING_BB
            if abc_bot.SB_BIGGER_OPEN_SIZING and position == "SB" and n_limpers == 0:
                bb = abc_bot.SB_OPEN_SIZING_BB
            amount = clamp(hand.big_blind * bb)
            presets[f"Open {bb:.1f}bb"] = amount
    elif n_raises == 1:
        raiser_seat = abc_bot._last_preflop_raiser_seat(hand)
        in_position = raiser_seat is not None and abc_bot._is_hero_in_position_vs_raiser(hand, seat, raiser_seat)
        mult = abc_bot.THREEBET_MULTIPLIER_IP if in_position else abc_bot.THREEBET_MULTIPLIER_OOP
        amount = clamp(hand.current_bet * mult)
        presets[f"3-бет {mult:.0f}x"] = amount
    # n_raises >= 2: the real strategy just shoves here (SHOVE_AA_KK_VS_3BET_PLUS;
    # SIZED_4BET_INSTEAD_OF_SHOVE was tested and confirmed negative, stays
    # off) -- nothing to add beyond the all-in preset below.

    presets["Ва-банк"] = max_to
    return presets


def build_raise_size_keyboard(session: BotSession) -> InlineKeyboardMarkup:
    is_preflop = session.hand.street == "preflop"
    presets = compute_preflop_raise_presets(session) if is_preflop else compute_raise_presets(session)
    buttons = [InlineKeyboardButton(f"{label} ({amount:.1f})", callback_data=f"raise:{label}") for label, amount in presets.items()]
    # 2 per row -- 4 buttons in one row truncates on a phone screen (real
    # user report: "Ва-банк (24" cut off mid-number).
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("« Назад", callback_data="act:back")])
    return InlineKeyboardMarkup(rows)


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


def build_hint_keyboard() -> InlineKeyboardMarkup:
    """The user's real feedback: the hint showed a recommendation with no
    way to actually take it -- one tap to just play it."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Сыграть по подсказке", callback_data="hint:play")]])


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
        rows.append(
            [
                InlineKeyboardButton(label, callback_data=f"drill:toggle:{flag}"),
                InlineKeyboardButton("ℹ️", callback_data=f"drill:info:{flag}"),
            ]
        )
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
        "а не раз в тысячу.\n\n"
        "Нажми ℹ️ у любого правила — покажу, что именно оно делает, почему это "
        "работает и насколько мы в нём уверены (реальные цифры из тестов, а не "
        "на глаз)."
    )


POSITIONS = ["UTG", "MP", "CO", "BTN", "SB"]


def build_ranges_position_keyboard() -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(pos, callback_data=f"ranges:{pos}") for pos in POSITIONS]
    return InlineKeyboardMarkup([row])


# ---- mode select: the very first thing /start shows, before any table exists ----


def render_mode_select_text() -> str:
    return (
        "<b>PokerDom</b>\n"
        "Выбери режим:"
    )


def build_mode_select_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎮 Обычная игра", callback_data="mode:normal")],
            [InlineKeyboardButton("🎯 Тренировка по правилам", callback_data="mode:drill")],
        ]
    )


# ---- persistent bottom menu (ReplyKeyboardMarkup, not attached to one
# message the way InlineKeyboardMarkup is -- stays under the text input
# until replaced) -- per explicit user request for a menu "как в других
# ботах ... не только с ответом на сообщение но и просто снизу". Button
# taps arrive as plain text messages (not callback_query), routed by
# bot.py's on_menu_button MessageHandler matching these exact strings. ----

MENU_HISTORY = "📜 История раздач"
MENU_RESET = "💰 Сбросить стол"
MENU_RULES = "📖 Все правила"
MENU_DRILL = "🎯 Тренировка"


def build_persistent_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(MENU_HISTORY), KeyboardButton(MENU_RESET)],
            [KeyboardButton(MENU_RULES), KeyboardButton(MENU_DRILL)],
        ],
        resize_keyboard=True,
    )


def render_hand_history_text(session: BotSession, limit: int = 10) -> str:
    if session.hand_history is None or not session.hand_history.entries:
        return "Пока нет завершённых раздач в этой сессии."
    lines = ["<b>История раздач</b> (последние):"]
    for summary in session.hand_history.list_summaries(limit=limit):
        sign = "+" if summary["hero_net"] >= 0 else ""
        mistake_part = f", ошибок: {summary['mistake_count']}" if summary["mistake_count"] else ""
        lines.append(f"#{summary['hand_number']}: {sign}{summary['hero_net']:.1f}bb{mistake_part}")
    return "\n".join(lines)
