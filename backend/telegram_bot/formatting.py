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

# Per-seat archetype emoji -- per user request ("хочу визуально знать с
# кем играю ... перед ботами с помощью эмодзи изображён его тип"),
# toggleable via settings ("archetype_emoji_enabled"). Not new information
# hero couldn't already see -- the hint panel already reveals archetype by
# name for the live aggressor -- just a faster-to-scan visual shorthand
# for every seat at once.
ARCHETYPE_EMOJI = {
    "Nit": "🔒",
    "TAG": "🎯",
    "LAG": "🔥",
    "Loose-passive": "🐟",
    "Station": "📞",
    "Maniac": "🤪",
}


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

    # This project's engine works in CHIPS (hand.big_blind=2.0 chips --
    # a 200-chip starting stack is documented elsewhere in this project
    # as "100bb effective", i.e. real bb = chips / big_blind). Every
    # display below divides by big_blind so "Xbb" here means real big
    # blinds, matching abc_bot.py's own _BB-named sizing constants --
    # per user report ("почему у нас опен 2.5bb это 5бб"), showing raw
    # chip counts suffixed "bb" was silently 2x-inflated everywhere.
    big_blind = hand.big_blind
    street = STREET_RU.get(hand.street, hand.street)
    pot = sum(p.total_contributed for p in hand.players.values())
    lines.append(f"<b>{street}</b>   Банк: {pot / big_blind:.1f}bb")
    lines.append(f"Борд: {_cards(hand.board)}")
    lines.append("")

    for seat in sorted(table.players):
        p = table.players[seat]
        marker = "👉 " if hand.current_actor() == seat else "   "
        tag = " (Вы)" if seat == session.hero_seat else ""
        position = _seat_position(hand, seat)
        # Dealer-button marker -- a distinct, real-poker "button chip"
        # visual next to whoever has it this hand, not just the [BTN]
        # text tag buried in the position label (per user request: "нужно
        # чтобы кнопка визуально была видна" -- "дилерская [фишка]").
        button = " 🔘" if seat == table.button_seat else ""
        state_bits = []
        if p.folded:
            state_bits.append("fold")
        if p.all_in:
            state_bits.append("all-in")
        if p.sitting_out:
            state_bits.append("вне игры")
        state = f" [{', '.join(state_bits)}]" if state_bits else ""
        cards = _cards(_visible_hole_cards(session, seat, p))
        archetype_emoji = ""
        if seat != session.hero_seat and session.settings.get("archetype_emoji_enabled", True) and session.turnover:
            archetype = session.turnover.archetype_for(seat)
            archetype_emoji = ARCHETYPE_EMOJI.get(archetype, "") + " "
        lines.append(
            f"{marker}[{position}]{button} {archetype_emoji}{p.name}{tag}: {p.stack / big_blind:.1f}bb "
            f"(ставка {p.street_contributed / big_blind:.1f}bb) {cards}{state}"
        )

    if hand.finished and hand.result is not None:
        lines.append("")
        lines.append("Раздача завершена. /newhand -- следующая.")
        review = render_hand_review(session)
        if review:
            lines.append("")
            lines.append(review)
    # No per-street feedback line mid-hand anymore -- per explicit user
    # request ("оценка должна появляться не когда прошла улица, а когда
    # закончилась раздача"), grading only shows once, in the full
    # render_hand_review above, when the hand actually ends. The
    # `trainer_feedback` param is kept (bot.py still computes and passes
    # it) since apply_hero_action's return value is used elsewhere, but
    # it's intentionally not rendered here anymore.

    return "\n".join(lines)


def _matches_abc_recommendation(d: dict, big_blind: float) -> bool:
    """Compares hero's actual action against choose_abc_action's own
    recommendation at that decision point -- action type must match, and
    for a raise/bet the amount must be reasonably close (within 10%, or
    0.5 real bb, whichever is bigger -- preset buttons and the strategy's
    own formula can differ by rounding). This is the ONLY grading logic
    used in the bot now -- no equity/CFR solver involved anywhere here,
    per explicit user request ("нужны советы не по солверу а по правилам
    абс бота"). `d["amount"]`/`d["abc_amount"]` are stored in CHIPS (see
    game.py); the 0.5-real-bb tolerance is converted to chips via
    big_blind so it means what it says regardless of the chip/bb ratio."""
    if d["action"] != d["abc_action"]:
        return False
    if d["action"] in ("raise", "bet") and d["amount"] is not None and d["abc_amount"] is not None:
        return abs(d["amount"] - d["abc_amount"]) <= max(0.5 * big_blind, d["abc_amount"] * 0.1)
    return True


def _format_action(action: str, amount: float | None, big_blind: float) -> str:
    """`amount` is in CHIPS (hand.apply_action's unit) -- divided by
    big_blind here so the displayed "bb" figure is a real big blind
    count, not a raw, 2x-inflated chip count (see build_raise_size_
    keyboard's docstring for the same conversion and why it's needed)."""
    action_ru = ACTION_RU.get(action, action)
    return f"{action_ru}" + (f" {amount / big_blind:.1f}bb" if amount else "")


def render_hand_review(session: BotSession) -> str:
    """Full per-street breakdown of EVERY hero decision this hand (not just
    the last one) -- what hero did vs what the ABC strategy
    (choose_abc_action) itself recommended at that exact point, ✅/❌ purely
    from whether they match. We don't attribute this to one specific
    abc_bot.py flag by name -- reliably pinpointing which of the ~30
    interacting rules drove a single decision would need much deeper
    instrumentation than exists today; this shows the strategy's actual
    recommendation instead, which is the honest thing we can compute."""
    decisions = session.street_decisions
    if not decisions:
        return ""
    big_blind = session.hand.big_blind
    lines = ["<b>Разбор по улицам (по правилам стратегии):</b>"]
    for d in decisions:
        street_ru = STREET_RU.get(d["street"], d["street"])
        match = _matches_abc_recommendation(d, big_blind)
        icon = "✅" if match else "❌"
        action_part = _format_action(d["action"], d["amount"], big_blind)
        lines.append(f"{icon} <b>{street_ru}</b>: вы — {action_part}")
        if not match:
            abc_part = _format_action(d["abc_action"], d["abc_amount"], big_blind)
            lines.append(f"   стратегия рекомендовала: {abc_part}")
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
        row.append(InlineKeyboardButton(f"Колл {legal['call_amount'] / hand.big_blind:.1f}bb", callback_data="act:call"))
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
    """Preflop preset raise-to amounts (in CHIPS -- hand.apply_action's
    unit -- NOT the "bb" unit these labels display; build_raise_size_
    keyboard converts for display, see its own docstring for why that
    conversion is needed).

    Scoped to the ONE real category that actually applies right now --
    per user correction ("у нас либо первый рейз либо 3бет"), a spot is
    either an opening/iso decision (n_raises==0) OR a 3-betting decision
    (n_raises==1), never both, so showing open+iso together with 3-bet
    sizing in the same menu doesn't reflect a real choice. WITHIN the
    applicable category, still shows every real sub-variant (open AND
    iso when unopened; both 3-bet multipliers when facing one raise) --
    per the earlier "все формулы, не только подходящие" request -- since
    those sub-variants genuinely are alternative real formulas for the
    same node, unlike open-vs-3bet which aren't both live at once."""
    hand = session.hand
    seat = session.hero_seat
    legal = hand.legal_actions(seat)
    notation = abc_bot._hand_notation(hand.players[seat].hole_cards)
    min_to, max_to = legal["min_raise_to"], legal["max_raise_to"]
    is_premium = notation in abc_bot.VALUE_3BET_TIGHT
    n_raises = _n_raises_this_street(hand)

    def clamp(x: float) -> float:
        return max(min_to, min(x, max_to))

    presets: dict[str, float] = {"Мин-рейз": min_to}

    if n_raises == 0:
        open_bb = abc_bot.OPEN_SIZING_BB + (abc_bot.PREMIUM_OPEN_SIZING_BONUS_BB if abc_bot.SIZE_UP_PREMIUM_OPENS and is_premium else 0)
        open_label = f"Open {open_bb:.1f}bb" + (" (премиум)" if abc_bot.SIZE_UP_PREMIUM_OPENS and is_premium else "")
        presets[open_label] = clamp(hand.big_blind * open_bb)

        if abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS:
            n_limpers = abc_bot._n_limpers_preflop(hand)
            iso_bb = abc_bot.TIGHT_ISO_BASE_SIZING_BB + abc_bot.TIGHT_ISO_SIZING_PER_LIMPER_BB * n_limpers
            iso_bb += abc_bot.PREMIUM_OPEN_SIZING_BONUS_BB if abc_bot.SIZE_UP_PREMIUM_OPENS and is_premium else 0
            presets[f"Изо {iso_bb:.1f}bb"] = clamp(hand.big_blind * iso_bb)
    elif n_raises == 1:
        # Both 3-bet multipliers (IP and OOP) -- per the earlier "all
        # formulas" request, still shown together since they ARE both
        # live real formulas for a facing-one-raise node (which one
        # matches hero's actual position doesn't change that both are
        # real strategy numbers worth comparing).
        if abc_bot.THREEBET_SIZE_BY_POSITION:
            for mult, tag in ((abc_bot.THREEBET_MULTIPLIER_IP, "IP"), (abc_bot.THREEBET_MULTIPLIER_OOP, "OOP")):
                presets[f"3-бет {mult:.0f}x ({tag})"] = clamp(hand.current_bet * mult)
        else:
            presets[f"3-бет {abc_bot.THREEBET_MULTIPLIER:.0f}x"] = clamp(hand.current_bet * abc_bot.THREEBET_MULTIPLIER)
    # n_raises >= 2: the real strategy just shoves here
    # (SHOVE_AA_KK_VS_3BET_PLUS; SIZED_4BET_INSTEAD_OF_SHOVE is off) --
    # nothing to add beyond min-raise/all-in.

    presets["Ва-банк"] = max_to
    return presets


def build_raise_size_keyboard(session: BotSession) -> InlineKeyboardMarkup:
    """Per user report ("почему у нас опен 2.5bb это 5bb"): this project's
    engine works in CHIPS (hand.big_blind=2.0 chips, e.g. a 200-chip
    starting stack = "100bb effective" per this project's own docs), but
    every preset LABEL above states a real-bb number directly (e.g.
    "Open 2.5bb" IS 2.5 real bb, by construction -- OPEN_SIZING_BB=2.5 is
    exactly abc_bot.py's own real-bb-denominated constant). The chip
    amount attached to each label must therefore be converted back to
    real bb (divide by hand.big_blind) before display, or the button
    shows two DIFFERENT numbers side by side that both claim to be "the
    size" (the label's real-bb figure vs the raw, 2x-inflated chip
    count) -- exactly the mismatch reported. hand.apply_action still gets
    the real, unconverted chip amount when the button is pressed (bot.py
    looks the label up in this same presets dict) -- only the DISPLAYED
    text changes here."""
    is_preflop = session.hand.street == "preflop"
    presets = compute_preflop_raise_presets(session) if is_preflop else compute_raise_presets(session)
    big_blind = session.hand.big_blind
    buttons = [
        InlineKeyboardButton(f"{label} ({amount / big_blind:.1f}bb)", callback_data=f"raise:{label}")
        for label, amount in presets.items()
    ]
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


def render_hint_text(hint: dict, big_blind: float) -> str:
    """Renders game.compute_abc_strategy_hint()'s output -- the ABC bot's
    own recommendation, fed the same live opponent reads a seated bot's
    decisions use, NOT an equity/CFR panel. `hint["amount"]` is in CHIPS
    (choose_abc_action's raw unit) -- divided by big_blind here for the
    same reason build_raise_size_keyboard does (real bb, not raw chips
    mislabeled "bb")."""
    action_ru = ACTION_RU.get(hint["action"], hint["action"])
    amount = hint["amount"]
    lines = ["<b>💡 Подсказка (наша стратегия)</b>"]
    rec_line = f"Рекомендация: <b>{action_ru}</b>"
    if amount is not None:
        rec_line += f" до {amount / big_blind:.1f}bb"
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
    emoji_label = "Эмодзи типов ботов: вкл ✅" if session.settings.get("archetype_emoji_enabled", True) else "Эмодзи типов ботов: выкл"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(hints_label, callback_data="settings:hints_toggle")],
            [InlineKeyboardButton(emoji_label, callback_data="settings:emoji_toggle")],
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
    # hero_net is in CHIPS (backend/hand_history.py's own unit) -- same
    # chips-vs-real-bb conversion as everywhere else in this module.
    # session.table (not session.hand) since history can be viewed with
    # no hand currently in progress.
    big_blind = session.table.big_blind if session.table else 1.0
    lines = ["<b>История раздач</b> (последние):"]
    for summary in session.hand_history.list_summaries(limit=limit):
        net_bb = summary["hero_net"] / big_blind
        sign = "+" if net_bb >= 0 else ""
        mistake_part = f", ошибок: {summary['mistake_count']}" if summary["mistake_count"] else ""
        lines.append(f"#{summary['hand_number']}: {sign}{net_bb:.1f}bb{mistake_part}")
    return "\n".join(lines)
