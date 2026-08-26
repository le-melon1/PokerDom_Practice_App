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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from backend.engine.hand import IllegalAction
from backend.telegram_bot import drills, formatting, game
from backend.telegram_bot.session import BotSession, SessionStore

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("pokerdom_telegram_bot")

store = SessionStore()


async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


async def _render_table(context: ContextTypes.DEFAULT_TYPE, session: BotSession, trainer_feedback: dict | None = None) -> None:
    text = formatting.render_table_text(session, trainer_feedback)
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
    of the web app's driveBotsIfNeeded polling loop."""
    while session.hand is not None and not session.hand.finished and session.hand.current_actor() != session.hero_seat:
        think_time = await _run(game.step_one_bot, session)
        store.save(session)
        await _render_table(context, session)
        if think_time:
            await asyncio.sleep(min(think_time, 2.5))


async def _deal_and_show(context: ContextTypes.DEFAULT_TYPE, session: BotSession) -> None:
    await _run(game.new_hand, session)
    store.save(session)
    await _render_table(context, session)
    await _run_bot_pacing_loop(context, session)
    store.save(session)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session, created = store.get_or_create(chat_id)
    if created:
        await _run(game.new_table, session)
        store.save(session)
        await context.bot.send_message(chat_id, "Стол готов. Раздаю первую руку...")
        await _deal_and_show(context, session)
        return
    if session.hand is None:
        await _deal_and_show(context, session)
    else:
        await _render_table(context, session)


async def newhand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = store.get(chat_id)
    if session is None or session.table is None:
        await context.bot.send_message(chat_id, "Сначала /start")
        return
    session.table_message_id = None  # start a fresh message for the new hand
    await _deal_and_show(context, session)


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = store.get(chat_id)
    if session is None:
        await context.bot.send_message(chat_id, "Сначала /start")
        return
    await context.bot.send_message(chat_id, "Настройки:", reply_markup=formatting.build_settings_keyboard(session))


async def drills_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = store.get(chat_id)
    if session is None:
        await context.bot.send_message(chat_id, "Сначала /start")
        return
    await context.bot.send_message(
        chat_id,
        formatting.render_drill_intro_text(),
        reply_markup=formatting.build_drill_root_keyboard(session),
        parse_mode="HTML",
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id
    session = store.get(chat_id)
    if session is None:
        await query.answer("Сначала /start", show_alert=True)
        return

    data = query.data
    await query.answer()

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
        await context.bot.send_message(chat_id, formatting.render_hint_text(hint), parse_mode="HTML")
        return

    if data == "settings:hints_toggle":
        session.settings["hints_enabled"] = not session.settings.get("hints_enabled", True)
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
        presets = formatting.compute_raise_presets(session)  # pure arithmetic, no need for to_thread
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

    if data == "drill:exit":
        session.settings["drill_flags"] = []
        await _run(game.new_table, session)
        store.save(session)
        await context.bot.send_message(chat_id, "Обычная игра. Стол сброшен.")
        session.table_message_id = None
        await _deal_and_show(context, session)
        return


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
    await _run_bot_pacing_loop(context, session)
    store.save(session)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set -- put it in .env (see @BotFather)")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newhand", newhand))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("drills", drills_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))

    logger.info("PokerDom Telegram bot starting (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
