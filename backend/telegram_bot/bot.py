"""Telegram bot entrypoint. Runs as its own process (`python -m
backend.telegram_bot.bot`), never started from or imported by backend/api.py
-- see backend/telegram_bot/session.py's module docstring for why the two
can't share state. Every engine/EV call is synchronous Python, wrapped in
asyncio.to_thread so it never blocks the bot's event loop (equity_trials=1500
Monte Carlo runs in estimate_live_ev/recommend_gto_action are the main
concern -- see backend/ev/live_ev.py).
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from backend.bots import abc_bot
from backend.engine.hand import IllegalAction
from backend.telegram_bot import disputes, drills, formatting, game, range_chart, rule_info
from backend.telegram_bot.session import BotSession, SessionStore

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("pokerdom_telegram_bot")

store = SessionStore()


async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


async def _render_table(context: ContextTypes.DEFAULT_TYPE, session: BotSession, trainer_feedback: dict | None = None) -> None:
    text = formatting.render_table_text(session, trainer_feedback)
    # Once the hand ends, offer new-hand / explain / dispute instead of no
    # keyboard at all (build_action_keyboard returns None once finished) --
    # per explicit user request.
    if session.hand is not None and session.hand.finished:
        keyboard = formatting.build_hand_finished_keyboard()
    else:
        keyboard = formatting.build_action_keyboard(session)
    if session.table_message_id is not None:
        try:
            await context.bot.edit_message_text(
                chat_id=session.chat_id,
                message_id=session.table_message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
            # message too old / deleted / edit window expired -- fall through and send a fresh one
    msg = await context.bot.send_message(chat_id=session.chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")
    session.table_message_id = msg.message_id


async def _run_bot_pacing_loop(context: ContextTypes.DEFAULT_TYPE, session: BotSession) -> None:
    """After hero acts, advance bot decisions one at a time with realistic
    pacing, editing the table message after each -- server-driven equivalent
    of the web app's driveBotsIfNeeded polling loop.

    Per user request: once hero has folded this hand, there's no one left
    who needs reading time for what the bots do -- hero isn't making any
    more decisions this hand, so the rest plays out with no artificial
    pauses at all (still one edited message per action, just back to back)."""
    hand = session.hand
    hero_folded = hand is not None and hand.players[session.hero_seat].folded
    while session.hand is not None and not session.hand.finished and session.hand.current_actor() != session.hero_seat:
        think_time = await _run(game.step_one_bot, session)
        store.save(session)
        await _render_table(context, session)
        if think_time and not hero_folded:
            await asyncio.sleep(min(think_time, 2.5))


AUTO_NEW_HAND_DELAY_SECONDS = 10.0


async def _auto_new_hand_after_delay(context: ContextTypes.DEFAULT_TYPE, session: BotSession, hand_number: int) -> None:
    await asyncio.sleep(AUTO_NEW_HAND_DELAY_SECONDS)
    # Skip if the user already started a new hand themselves (manual "🆕
    # Новая раздача", /newhand, a table reset, etc.) or the hand somehow
    # isn't finished anymore by the time this wakes up.
    if session.hand_number != hand_number:
        return
    if session.hand is None or not session.hand.finished:
        return
    session.table_message_id = None
    await _deal_and_show(context, session)


def _schedule_auto_new_hand(context: ContextTypes.DEFAULT_TYPE, session: BotSession) -> None:
    """Per user request ("пусть новая раздача начинается сама по себе
    после завершения раздачи"): a finished hand rolls into the next one on
    its own after a short delay, instead of always requiring "🆕 Новая
    раздача". Runs as a background task rather than an inline `await` so
    this handler returns immediately and the post-hand buttons (explain/
    dispute/history) stay responsive during the wait -- this bot's
    Application processes updates sequentially by default (no job-queue
    extra installed here), so sleeping inline would have blocked every
    other button press in this chat until the delay finished."""
    if session.hand is None or not session.hand.finished:
        return
    asyncio.create_task(_auto_new_hand_after_delay(context, session, session.hand_number))


async def _deal_and_show(context: ContextTypes.DEFAULT_TYPE, session: BotSession) -> None:
    await _run(game.new_hand, session)
    store.save(session)
    await _render_table(context, session)
    await _run_bot_pacing_loop(context, session)
    store.save(session)
    _schedule_auto_new_hand(context, session)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start always begins fresh: shows the mode-select menu instead of
    jumping straight into a hand, and does NOT touch any existing
    table/hand yet -- that only happens once a mode is actually picked
    (mode:normal / mode:drill below), matching the user's explicit ask
    ("надо чтобы когда я вводил старт игра начиналась заново, и вообще
    надо начинать не с игры а с выбора режима")."""
    chat_id = update.effective_chat.id
    session, _ = store.get_or_create(chat_id)
    session.table_message_id = None  # next table render starts a fresh message
    store.save(session)
    # Persistent bottom menu (ReplyKeyboardMarkup) -- a separate message,
    # since one message can only carry one kind of reply_markup and the
    # mode-select choice below needs InlineKeyboardMarkup. Once sent it
    # stays under the text input for the rest of the chat, not just this
    # one message -- per explicit user request for a menu "как в других
    # ботах ... не только с ответом на сообщение но и просто снизу".
    await context.bot.send_message(chat_id, "Меню снизу 👇", reply_markup=formatting.build_persistent_menu())
    await context.bot.send_message(
        chat_id,
        formatting.render_mode_select_text(),
        reply_markup=formatting.build_mode_select_keyboard(),
        parse_mode="HTML",
    )


async def newhand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = store.get(chat_id)
    if session is None or session.table is None:
        await context.bot.send_message(chat_id, "Сначала /start и выбери режим")
        return
    session.table_message_id = None  # start a fresh message for the new hand
    await _deal_and_show(context, session)


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = store.get(chat_id)
    if session is None:
        await context.bot.send_message(chat_id, "Сначала /start и выбери режим")
        return
    await context.bot.send_message(chat_id, "Настройки:", reply_markup=formatting.build_settings_keyboard(session))


async def ranges_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id,
        "Выбери позицию — покажу открывающий диапазон (наша реальная стратегия, не теория из книги).",
        reply_markup=formatting.build_ranges_position_keyboard(),
    )


async def drills_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = store.get(chat_id)
    if session is None:
        await context.bot.send_message(chat_id, "Сначала /start и выбери режим")
        return
    await context.bot.send_message(
        chat_id,
        formatting.render_drill_intro_text(),
        reply_markup=formatting.build_drill_root_keyboard(session),
        parse_mode="HTML",
    )


async def on_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes taps on the persistent bottom ReplyKeyboardMarkup -- these
    arrive as plain text messages, not callback_query, so they need their
    own handler rather than on_callback."""
    chat_id = update.effective_chat.id
    text = update.message.text
    session = store.get(chat_id)
    if session is None:
        await context.bot.send_message(chat_id, "Сначала /start и выбери режим")
        return

    # A dispute comment is awaited (user picked "⚠️ Оспорить совет" and a
    # specific street) -- this message IS the comment, not a menu tap.
    if session.pending_dispute is not None:
        await _save_pending_dispute(session, comment=text)
        await context.bot.send_message(chat_id, "Спасибо, записал ваш комментарий.")
        return

    if text == formatting.MENU_HISTORY:
        await context.bot.send_message(chat_id, formatting.render_hand_history_text(session), parse_mode="HTML")
        return

    if text == formatting.MENU_RESET:
        session.settings["drill_flags"] = []
        await _run(game.new_table, session)
        store.save(session)
        session.table_message_id = None
        await context.bot.send_message(chat_id, "Стол сброшен, деньги заново.")
        await _deal_and_show(context, session)
        return

    if text == formatting.MENU_RULES or text == formatting.MENU_DRILL:
        await context.bot.send_message(
            chat_id,
            formatting.render_drill_intro_text(),
            reply_markup=formatting.build_drill_root_keyboard(session),
            parse_mode="HTML",
        )
        return


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id
    session = store.get(chat_id)
    if session is None:
        await query.answer("Сначала /start и выбери режим", show_alert=True)
        return

    data = query.data
    await query.answer()

    if data == "mode:normal":
        session.settings["drill_flags"] = []
        await _run(game.new_table, session)
        store.save(session)
        session.table_message_id = None
        await _deal_and_show(context, session)
        return

    if data == "mode:drill":
        await query.edit_message_text(
            formatting.render_drill_intro_text(),
            reply_markup=formatting.build_drill_root_keyboard(session),
            parse_mode="HTML",
        )
        return

    if data == "act:raise_menu":
        await query.edit_message_reply_markup(reply_markup=formatting.build_raise_size_keyboard(session))
        return

    if data == "act:back":
        await query.edit_message_reply_markup(reply_markup=formatting.build_action_keyboard(session))
        return

    if data == "hint:show":
        try:
            hint = await _run(game.compute_abc_strategy_hint, session)
        except RuntimeError:
            return
        await context.bot.send_message(
            chat_id,
            formatting.render_hint_text(hint, session.hand.big_blind),
            reply_markup=formatting.build_hint_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == "hint:play":
        try:
            hint = await _run(game.compute_abc_strategy_hint, session)
        except RuntimeError:
            return
        await _apply_action_and_continue(context, session, hint["action"], hint["amount"])
        return

    if data == "settings:hints_toggle":
        session.settings["hints_enabled"] = not session.settings.get("hints_enabled", True)
        store.save(session)
        await query.edit_message_reply_markup(reply_markup=formatting.build_settings_keyboard(session))
        return

    if data == "settings:emoji_toggle":
        session.settings["archetype_emoji_enabled"] = not session.settings.get("archetype_emoji_enabled", True)
        store.save(session)
        await query.edit_message_reply_markup(reply_markup=formatting.build_settings_keyboard(session))
        return

    if data == "settings:freqtier_toggle":
        session.settings["freq_tier_emoji_enabled"] = not session.settings.get("freq_tier_emoji_enabled", True)
        store.save(session)
        await query.edit_message_reply_markup(reply_markup=formatting.build_settings_keyboard(session))
        return

    if data == "settings:reset":
        await _run(game.new_table, session)
        store.save(session)
        await context.bot.send_message(chat_id, "Стол сброшен.")
        await _deal_and_show(context, session)
        return

    if data.startswith("act:"):
        action = data.split(":", 1)[1]
        await _apply_action_and_continue(context, session, action, None)
        return

    if data.startswith("raise:"):
        label = data.split(":", 1)[1]
        # pure arithmetic, no to_thread needed -- street-aware, matches build_raise_size_keyboard
        is_preflop = session.hand is not None and session.hand.street == "preflop"
        presets = formatting.compute_preflop_raise_presets(session) if is_preflop else formatting.compute_raise_presets(session)
        amount = presets.get(label)
        if amount is None:
            return
        await _apply_action_and_continue(context, session, "raise", amount)
        return

    if data == "drill:root":
        await query.edit_message_text(
            formatting.render_drill_intro_text(),
            reply_markup=formatting.build_drill_root_keyboard(session),
            parse_mode="HTML",
        )
        return

    if data.startswith("drill:stage:"):
        stage = data.split(":", 2)[2]
        await query.edit_message_reply_markup(reply_markup=formatting.build_drill_category_keyboard(stage))
        return

    if data.startswith("drill:cat:"):
        category = data.split(":", 2)[2]
        await query.edit_message_reply_markup(reply_markup=formatting.build_drill_flag_keyboard(session, category))
        return

    if data.startswith("drill:toggle:"):
        flag = data.split(":", 2)[2]
        selected = list(session.settings.get("drill_flags") or [])
        if flag in selected:
            selected.remove(flag)
        else:
            selected.append(flag)
        session.settings["drill_flags"] = selected
        store.save(session)
        category = drills.FLAG_CATEGORY.get(flag)
        if category:
            await query.edit_message_reply_markup(reply_markup=formatting.build_drill_flag_keyboard(session, category))
        return

    if data == "drill:start":
        await _run(game.new_table, session)
        store.save(session)
        labels = [drills.FLAG_LABEL_RU.get(f, f) for f in session.settings.get("drill_flags") or []]
        await context.bot.send_message(chat_id, f"🎯 Тренировка начата: {', '.join(labels)}")
        session.table_message_id = None
        await _deal_and_show(context, session)
        return

    if data.startswith("ranges:"):
        position = data.split(":", 1)[1]
        await _send_position_range(context, chat_id, position)
        return

    if data.startswith("drill:info:"):
        flag = data.split(":", 2)[2]
        await _send_rule_info(context, chat_id, flag)
        return

    if data == "drill:exit":
        session.settings["drill_flags"] = []
        await _run(game.new_table, session)
        store.save(session)
        await context.bot.send_message(chat_id, "Обычная игра. Стол сброшен.")
        session.table_message_id = None
        await _deal_and_show(context, session)
        return

    # Post-hand buttons -- per explicit user request: new hand / explain
    # the strategy's advice / dispute a specific decision (pick which one,
    # optionally comment, gets logged to disputes.py for later review).
    if data == "hand:new":
        session.table_message_id = None
        await _deal_and_show(context, session)
        return

    if data == "hand:explain":
        await context.bot.send_message(chat_id, formatting.render_explain_text(session), parse_mode="HTML")
        return

    if data == "hand:history":
        await context.bot.send_message(chat_id, formatting.render_action_history_text(session), parse_mode="HTML")
        return

    if data == "hand:dispute":
        if not session.street_decisions:
            await context.bot.send_message(chat_id, "В этой раздаче не было ваших решений.")
            return
        await context.bot.send_message(
            chat_id,
            "С каким советом вы не согласны?",
            reply_markup=formatting.build_dispute_pick_keyboard(session),
        )
        return

    if data == "hand:cancel_dispute":
        session.pending_dispute = None
        store.save(session)
        await query.edit_message_text("Отменено.")
        return

    if data.startswith("dispute:pick:"):
        idx = int(data.split(":", 2)[2])
        if idx < 0 or idx >= len(session.street_decisions):
            return
        session.pending_dispute = dict(session.street_decisions[idx])
        session.pending_dispute["hand_number"] = session.hand_number
        store.save(session)
        await query.edit_message_text(
            "Можете написать комментарий (или нажмите «Без комментария»).",
            reply_markup=formatting.build_dispute_comment_keyboard(),
        )
        return

    if data == "dispute:nocomment":
        await _save_pending_dispute(session, comment="")
        await query.edit_message_text("Спасибо, записал без комментария.")
        return


def _build_open_range_photo(position: str) -> tuple[bytes, str]:
    open_ranges, *_ = abc_bot._ranges()
    hand_set = open_ranges.get(position, set())
    vpip = abc_bot.OPEN_VPIP_BY_POSITION.get(position)
    caption = f"Открывающий диапазон: {position} ({len(hand_set)} рук, целевой VPIP {vpip * 100:.1f}%)" if vpip else f"Открывающий диапазон: {position}"
    png = range_chart.render_range_chart(hand_set, title=f"Open range: {position}")
    return png, caption


async def _send_position_range(context: ContextTypes.DEFAULT_TYPE, chat_id: int, position: str) -> None:
    png, caption = await _run(_build_open_range_photo, position)
    await context.bot.send_photo(chat_id, photo=png, caption=caption)


async def _save_pending_dispute(session: BotSession, comment: str) -> None:
    d = session.pending_dispute
    if d is None:
        return
    dispute = disputes.Dispute(
        chat_id=session.chat_id,
        hand_number=d.get("hand_number", session.hand_number),
        street=d["street"],
        hero_action=d["action"],
        hero_amount=d["amount"],
        abc_action=d["abc_action"],
        abc_amount=d["abc_amount"],
        comment=comment,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await _run(disputes.record_dispute, dispute)
    session.pending_dispute = None
    store.save(session)


async def _send_rule_info(context: ContextTypes.DEFAULT_TYPE, chat_id: int, flag: str) -> None:
    text = rule_info.render_rule_info_text(flag)
    chart = await _run(rule_info.chart_notations_for, flag)
    if chart is not None:
        hand_set, subtitle = chart
        title = drills.FLAG_LABEL_RU.get(flag, flag)
        png = await _run(range_chart.render_range_chart, hand_set, f"{title} ({subtitle})")
        await context.bot.send_photo(chat_id, photo=png, caption=f"{len(hand_set)} рук — {subtitle}")
    await context.bot.send_message(chat_id, text, parse_mode="HTML")


async def _apply_action_and_continue(
    context: ContextTypes.DEFAULT_TYPE, session: BotSession, action: str, amount: float | None
) -> None:
    try:
        feedback = await _run(game.apply_hero_action, session, action, amount)
    except (RuntimeError, IllegalAction) as e:
        logger.info("illegal action from chat %s: %s", session.chat_id, e)
        return
    store.save(session)
    await _render_table(context, session, trainer_feedback=feedback)
    # A gap between showing hero's own action and the first bot's reaction
    # -- previously missing, so if the first bot happened to act fast the
    # two updates could land close enough together to blur into one. Same
    # "hero already folded, no one needs reading time" exception as the
    # bot pacing loop below -- skip it there too.
    hand = session.hand
    hero_folded = hand is not None and hand.players[session.hero_seat].folded
    if not hero_folded:
        await asyncio.sleep(1.0)
    await _run_bot_pacing_loop(context, session)
    store.save(session)
    _schedule_auto_new_hand(context, session)


# Registered via set_my_commands (post_init below) so Telegram shows this
# list the instant the user types "/" -- per explicit user request.
BOT_COMMANDS = [
    BotCommand("start", "Начать / выбрать режим (сбрасывает игру)"),
    BotCommand("newhand", "Новая раздача"),
    BotCommand("drills", "Тренировка по правилам"),
    BotCommand("ranges", "Диапазоны открытия по позиции"),
    BotCommand("settings", "Настройки"),
]


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(BOT_COMMANDS)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set -- put it in .env (see @BotFather)")

    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newhand", newhand))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("drills", drills_cmd))
    app.add_handler(CommandHandler("ranges", ranges_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_menu_button))

    logger.info("PokerDom Telegram bot starting (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
