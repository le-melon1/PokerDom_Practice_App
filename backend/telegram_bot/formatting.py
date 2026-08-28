"""Pure functions: Hand/Table/session -> Telegram message text +
InlineKeyboardMarkup. No poker logic here -- everything is read from what
game.py / the engine already computed."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from backend.bots import abc_bot
from backend.bots.behavior_clone import _n_raises_this_street
from backend.telegram_bot import drills, game
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

# Per-seat postflop_freq_tier emoji -- per user request ("у нас не показана
# в эмодзи степень игры на постфлопе, пусть будет кружочка трёх разных
# цветов"). Independent axis from archetype (see abc_bot.py's 2026-08-19/20
# restructure -- preflop archetype and postflop aggression frequency were
# split apart on purpose), so its own emoji slot, toggleable via settings
# ("freq_tier_emoji_enabled") the same way archetype_emoji_enabled is.
FREQ_TIER_EMOJI = {"rare": "⬇️", "normal": "🔸", "often": "🔺"}


def _card(card: str) -> str:
    if card == "??":
        return "🂠"
    rank, suit = card[0], card[1]
    return f"{rank}{SUIT_EMOJI.get(suit, suit)}"


def _cards(cards: list[str]) -> str:
    if not cards:
        return "-"
    return " ".join(_card(c) for c in cards)


def _seats_who_raised_this_street(hand) -> set[int]:
    """Per user request ("можем подкрашивать текст когда боты рейзят") --
    Telegram's HTML has no real text-color entity, so this marks a raiser
    with an emoji instead. Hand.actions (models.ActionRecord) already logs
    every action with its own street/seat/kind -- street_contributed alone
    can't tell a raiser from a caller once both match the same bet amount,
    but the action log can: take each seat's LAST action this street, keep
    the ones whose kind is "raises"/"bets" (a player who bet/raised and was
    then re-raised has "calls" or "folds" as their real last action, so
    they correctly drop out of this set)."""
    last_by_seat: dict[int, str] = {}
    for a in hand.actions:
        if a.street == hand.street:
            last_by_seat[a.seat] = a.action
    return {seat for seat, action in last_by_seat.items() if action in ("raises", "bets")}


def _struck_row(slots: list[str], rest: str) -> str:
    """Strikethrough for a folded row, but Telegram doesn't draw the <s>
    line through emoji glyphs -- wrapping the whole row left it visibly
    broken (text struck, emoji not). Wraps only the plain-text spans and
    leaves each real emoji slot unwrapped, so the strike runs right up to
    each emoji instead of skipping a gap or covering the row inconsistently
    (per user: "перечёркивание оставляй, просто чтобы он доходил до
    эмодзи"). `slots` is the row's left-side markers in order (turn/dealer/
    archetype/freq-tier); mirrors the non-folded row's exact concatenation
    (f"{' '.join(slots)} {rest}") segment-for-segment, so folded and
    non-folded rows still line up with each other -- only which spans get
    wrapped in <s> differs."""
    segments: list[tuple[str, bool]] = []
    for i, slot in enumerate(slots):
        if i > 0:
            segments.append((" ", False))
        segments.append((slot, bool(slot.strip())))
    segments.append((" ", False))
    segments.append((rest, False))

    out = []
    buf = ""
    for text, is_emoji in segments:
        if is_emoji:
            if buf:
                out.append(f"<s>{buf}</s>")
                buf = ""
            out.append(text)
        else:
            buf += text
    if buf:
        out.append(f"<s>{buf}</s>")
    return "".join(out)


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
    lines.append(f"<b>{street}</b>   Банк: {pot / big_blind:.1f}")
    lines.append(f"Борд: {_cards(hand.board)}")
    lines.append("")

    raised_seats = _seats_who_raised_this_street(hand)
    for seat in sorted(table.players):
        p = table.players[seat]
        is_current_actor = hand.current_actor() == seat
        # Left-side "slots" (turn marker, dealer chip, archetype emoji,
        # postflop_freq_tier emoji), each ALWAYS a fixed-width placeholder
        # when the real emoji
        # isn't present, so a row's name/stack/bet never shifts right
        # depending on which of these happen to be present this hand. Per
        # user reports (with screenshots) this kept drifting no matter how
        # many plain spaces were used. A "|" swap (tried previously) likely
        # moved the wrong direction -- the usual cross-platform convention
        # (same one terminals use for CJK/emoji) treats a color emoji as
        # roughly DOUBLE the width of a normal letter, and a plain space is
        # itself narrower than a letter -- so an emoji is closer to ~4
        # spaces wide, not 2-3. Widened to 4 plain spaces on that basis.
        # Still an estimate, not a pixel measurement I can actually verify
        # without seeing the render -- expect another screenshot round.
        marker = "👉" if is_current_actor else "    "
        # Just "Вы", not the engine's internal "Hero" name -- per user
        # request ("слово hero из игры можно убрать оставить только вы").
        display_name = "Вы" if seat == session.hero_seat else p.name
        # Dealer-button marker -- a distinct, real-poker "button chip"
        # visual next to whoever has it this hand (per user request: "нужно
        # чтобы кнопка визуально была видна" -- "дилерская [фишка]"). Per a
        # later request ("убери надписи позиций... и так понятно если есть
        # фишка дилера"), the separate [UTG]/[BTN]/etc. text tag was
        # removed -- the button chip alone conveys position well enough.
        button = "🔘" if seat == table.button_seat else "    "
        state_bits = []
        # No "fold" tag -- per user request ("убери у ботов надпись фолд
        # и перевёрнутые карты, это и так понятно"): a folded seat just
        # stops acting and stops showing cards, that's enough.
        if p.all_in:
            state_bits.append("all-in")
        if p.sitting_out:
            state_bits.append("вне игры")
        state = f" [{', '.join(state_bits)}]" if state_bits else ""
        hole_cards = _visible_hole_cards(session, seat, p)
        cards = _cards(hole_cards) if hole_cards else ""
        archetype_emoji = "    "
        # No archetype emoji for a folded bot -- per user request ("чтобы
        # не играющие не сбивали при игре"): a folded seat is out of the
        # hand, so its type icon is just visual noise while you're reading
        # who's still live -- same blank placeholder as if archetype
        # emoji were off entirely.
        if not p.folded and seat != session.hero_seat and session.settings.get("archetype_emoji_enabled", True) and session.turnover:
            archetype = session.turnover.archetype_for(seat)
            emoji = ARCHETYPE_EMOJI.get(archetype, "")
            if emoji:
                archetype_emoji = emoji
        freq_tier_emoji = "    "
        if not p.folded and seat != session.hero_seat and session.settings.get("freq_tier_emoji_enabled", True) and session.turnover:
            freq_tier = session.turnover.freq_tier_for(seat)
            emoji = FREQ_TIER_EMOJI.get(freq_tier, "")
            if emoji:
                freq_tier_emoji = emoji
        # Fixed-width padding on the name/stack/bet columns -- per user
        # request ("поставь правильное количество пробелов для красивого
        # форматирования"). Telegram's plain message text isn't
        # monospace (a <pre> block that forced real alignment was tried
        # and reverted -- "очень плохо выглядит"), so this is an
        # approximation, not pixel-perfect column alignment, but it keeps
        # every row's name/stack/bet field the same character count.
        name_col = f"{display_name:<6}"
        stack_col = f"{p.stack / big_blind:>6.1f}"
        bet_col = f"{p.street_contributed / big_blind:>5.1f}"
        raise_marker = " ⬆️" if seat in raised_seats else ""
        # No trailing "-" placeholder when there's nothing to show (per
        # user: "у ботов после ставки бессмысленно там же нет ничего") --
        # only hero's own cards or a real showdown reveal render anything
        # in the cards slot now (see _visible_hole_cards), so an empty
        # cards string just means genuinely nothing to display.
        cards_part = f" {cards}" if cards else ""
        rest = f"{name_col}: {stack_col} (ставка {bet_col}){raise_marker}{cards_part}{state}"
        # Strikethrough marks a folded row, but Telegram doesn't draw the
        # <s> line through emoji glyphs (button chip/archetype emoji) --
        # _struck_row wraps only the plain-text spans so the strike runs
        # right up to each emoji instead of leaving it looking broken
        # (per user: "перечёркивание оставляй, просто чтобы он доходил до
        # эмодзи"). Bold highlights whose turn it is now (on top of the
        # existing 👉 marker); folded and current-actor are mutually
        # exclusive (a folded seat is never on turn).
        slots = [marker, button, archetype_emoji, freq_tier_emoji]
        if p.folded:
            row = _struck_row(slots, rest)
        else:
            row = f"{' '.join(slots)} {rest}"
            if is_current_actor:
                row = f"<b>{row}</b>"
        lines.append(row)

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
    return f"{action_ru}" + (f" {amount / big_blind:.1f}" if amount else "")


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


def render_explain_text(session: BotSession) -> str:
    """"❓ Объяснить советы" -- unlike render_hand_review (which only shows
    the strategy's side when hero DIDN'T match it), this walks every street
    and always states both sides plainly, for whoever wants the full
    picture regardless of whether they agreed. Same honesty limit as
    render_hand_review: no specific abc_bot.py flag is named, since nothing
    in this codebase yet traces a single decision back to which of the
    ~30 interacting rules actually drove it -- points at /drills' own
    per-rule ℹ️ pages instead, which DO have real confidence/stats."""
    decisions = session.street_decisions
    if not decisions:
        return "Пока нет решений в этой раздаче."
    big_blind = session.hand.big_blind if session.hand else 1.0
    lines = ["<b>Объяснение решений стратегии по улицам</b>"]
    for d in decisions:
        street_ru = STREET_RU.get(d["street"], d["street"])
        your_part = _format_action(d["action"], d["amount"], big_blind)
        abc_part = _format_action(d["abc_action"], d["abc_amount"], big_blind)
        match = _matches_abc_recommendation(d, big_blind)
        lines.append(f"\n<b>{street_ru}</b>")
        lines.append(f"Вы: {your_part}")
        lines.append(f"Стратегия: {abc_part}" + (" (совпадает)" if match else " (не совпадает)"))
    lines.append(
        "\nПодробности по конкретным правилам -- через /drills → ℹ️ у нужного "
        "правила (там есть уверенность и реальная статистика по нему)."
    )
    return "\n".join(lines)


def build_hand_finished_keyboard() -> InlineKeyboardMarkup:
    """Shown once a hand ends, per explicit user request -- new
    hand / explain the strategy's advice / dispute a specific decision."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🆕 Новая раздача", callback_data="hand:new")],
            [InlineKeyboardButton("❓ Объяснить советы", callback_data="hand:explain")],
            [InlineKeyboardButton("⚠️ Оспорить совет", callback_data="hand:dispute")],
        ]
    )


def build_dispute_pick_keyboard(session: BotSession) -> InlineKeyboardMarkup:
    """One button per street decision this hand, so the user picks
    EXACTLY which recommendation they disagree with (per user: "выбирает
    совет с которым не согласен")."""
    big_blind = session.hand.big_blind if session.hand else 1.0
    rows = []
    for i, d in enumerate(session.street_decisions):
        street_ru = STREET_RU.get(d["street"], d["street"])
        abc_part = _format_action(d["abc_action"], d["abc_amount"], big_blind)
        rows.append([InlineKeyboardButton(f"{street_ru}: {abc_part}", callback_data=f"dispute:pick:{i}")])
    rows.append([InlineKeyboardButton("« Отмена", callback_data="hand:cancel_dispute")])
    return InlineKeyboardMarkup(rows)


def build_dispute_comment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Без комментария", callback_data="dispute:nocomment")],
            [InlineKeyboardButton("« Отмена", callback_data="hand:cancel_dispute")],
        ]
    )


def _visible_hole_cards(session: BotSession, seat: int, player) -> list[str]:
    # No face-down "🂠 🂠" placeholder for a live bot's hidden hand anymore
    # -- per user request ("убери у ботов ... перевёрнутые карты, это и
    # так понятно"): an opponent obviously has two hidden cards, showing a
    # placeholder icon for that isn't new information. Only hero's own
    # cards and a real showdown reveal are worth actually displaying.
    hand = session.hand
    if seat == session.hero_seat:
        return player.hole_cards
    if hand is None:
        return []
    real_showdown = hand.finished and hand.result is not None and len(hand.result.winners_by_pot) > 0
    if real_showdown and player.in_hand:
        return player.hole_cards
    return []


def build_action_keyboard(session: BotSession) -> InlineKeyboardMarkup | None:
    hand = session.hand
    if hand is None or hand.finished or hand.current_actor() != session.hero_seat:
        return None
    legal = hand.legal_actions(session.hero_seat)

    # Per user request: fold=red, check/call=green, raise=blue -- Bot API's
    # per-button "style" (python-telegram-bot 22.7+, Telegram clients
    # released after 2026-02-09; older clients just show unstyled buttons).
    row = [InlineKeyboardButton("Фолд", callback_data="act:fold", style=KeyboardButtonStyle.DANGER)]
    if legal["can_check"]:
        row.append(InlineKeyboardButton("Чек", callback_data="act:check", style=KeyboardButtonStyle.SUCCESS))
    else:
        row.append(
            InlineKeyboardButton(
                f"Колл {legal['call_amount'] / hand.big_blind:.1f}",
                callback_data="act:call",
                style=KeyboardButtonStyle.SUCCESS,
            )
        )
    if legal["max_raise_to"] > legal["min_raise_to"] - 1e-9:
        row.append(InlineKeyboardButton("Рейз/Бет", callback_data="act:raise_menu", style=KeyboardButtonStyle.PRIMARY))

    rows = [row]
    if session.settings.get("hints_enabled"):
        rows.append([InlineKeyboardButton("💡 Подсказка", callback_data="hint:show")])
    return InlineKeyboardMarkup(rows)


def compute_raise_presets(session: BotSession) -> dict[str, float]:
    """Postflop preset raise-to (absolute) amounts.

    Postflop sizing in abc_bot.py isn't one flat pot-fraction the way this
    function used to assume -- it's chosen from 14 different POT_FRACTION
    constants (BIG_VALUE_SIZING_POT_FRACTION=0.75, STANDARD_SIZING_
    POT_FRACTION=0.50, RIVER/TURN_OVERBET=1.5, DRY_CBET=0.33, BLOCK_BET=0.3,
    etc.), gated by a genuinely multi-dimensional condition space (hand
    strength, board texture, initiative, street, opponent archetype) --
    unlike preflop's simple n_raises/n_limpers branching (see
    compute_preflop_raise_presets), there's no small, reliable set of
    "the applicable category" to hand-replicate here without risking the
    exact bug this is fixing (real report: strategy recommended 14.6bb,
    the closest generic-fraction button was nowhere near it -- "но у меня
    даже такого варианта не было").

    So instead of guessing which of the 14 formulas applies, ask
    choose_abc_action directly what IT would do here (the exact same call
    render_hand_review already uses to grade hero after the fact) and
    guarantee that exact amount is always one of the buttons -- correct by
    construction, and can never drift out of sync with the real strategy
    the way a hand-copied formula could. The generic pot-fraction tiers
    stay alongside it for manual what-if exploration."""
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

    presets: dict[str, float] = {}

    abc_action, abc_amount = game._abc_recommendation(session)
    if abc_action in ("raise", "bet") and abc_amount is not None:
        presets["Как стратегия"] = clamp(abc_amount)

    presets["1/3 пота"] = clamp(base + 0.33 * pot_after_call)
    presets["1/2 пота"] = clamp(base + 0.5 * pot_after_call)
    presets["Пот"] = clamp(base + 1.0 * pot_after_call)
    presets["Ва-банк"] = max_to
    return presets


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
        open_label = f"Open {open_bb:.1f}" + (" (премиум)" if abc_bot.SIZE_UP_PREMIUM_OPENS and is_premium else "")
        presets[open_label] = clamp(hand.big_blind * open_bb)

        # Only offer "Изо" when there's actually a limper to isolate --
        # choose_abc_action's own gate is `use_tight_big_iso =
        # TIGHT_BIG_ISO_RAISE_LIMPERS and n_limpers >= 1` (abc_bot.py).
        # Showing this preset at n_limpers==0 offered a sizing the
        # strategy would never actually pick in that spot (it opens with
        # the plain Open formula instead) -- found while checking the
        # premium-hand sizing bonus applies correctly to both opens and
        # isos (real hand: AA+0 limpers -> abc picks "Open 4.0", not the
        # "Изо 7.0" this used to also show side by side).
        n_limpers = abc_bot._n_limpers_preflop(hand)
        if abc_bot.TIGHT_BIG_ISO_RAISE_LIMPERS and n_limpers >= 1:
            iso_bb = abc_bot.TIGHT_ISO_BASE_SIZING_BB + abc_bot.TIGHT_ISO_SIZING_PER_LIMPER_BB * n_limpers
            iso_bb += abc_bot.PREMIUM_OPEN_SIZING_BONUS_BB if abc_bot.SIZE_UP_PREMIUM_OPENS and is_premium else 0
            presets[f"Изо {iso_bb:.1f}"] = clamp(hand.big_blind * iso_bb)
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
        InlineKeyboardButton(
            f"{label} ({amount / big_blind:.1f})", callback_data=f"raise:{label}", style=KeyboardButtonStyle.PRIMARY
        )
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
        rec_line += f" до {amount / big_blind:.1f}"
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
    freq_tier_label = (
        "Эмодзи частоты на постфлопе: вкл ✅" if session.settings.get("freq_tier_emoji_enabled", True) else "Эмодзи частоты на постфлопе: выкл"
    )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(hints_label, callback_data="settings:hints_toggle")],
            [InlineKeyboardButton(emoji_label, callback_data="settings:emoji_toggle")],
            [InlineKeyboardButton(freq_tier_label, callback_data="settings:freqtier_toggle")],
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
        lines.append(f"#{summary['hand_number']}: {sign}{net_bb:.1f}{mistake_part}")
    return "\n".join(lines)
