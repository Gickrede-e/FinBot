import csv
import io
import logging
import os
from typing import Optional

import telebot
from dotenv import load_dotenv
from telebot import apihelper, types

from models import (
    DEFAULT_BANKS,
    Bank,
    add_bank,
    count_users,
    delete_bank,
    ensure_user,
    get_connection,
    get_setting,
    init_db,
    list_banks,
    referrals_by_bank,
    set_setting,
    top_referrers,
    update_bank_url,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_WELCOME_TEXT = (
    "👋 Привет! Это реферальный бот. Выберите банк ниже, чтобы получить свою ссылку."
)


def build_bank_keyboard(banks: list[Bank], referral_code: int) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for bank in banks:
        url = f"{bank.base_url}?ref={referral_code}"
        keyboard.add(types.InlineKeyboardButton(text=bank.key, url=url))
    return keyboard


def start_handler(
    message: types.Message,
    bot: telebot.TeleBot,
    db_path: str,
    banks: list[Bank],
    welcome_text: str,
) -> None:
    user = message.from_user
    if user is None:
        return

    with get_connection(db_path) as conn:
        ensure_user(
            conn,
            user.id,
            user.username,
            user.first_name,
            user.last_name,
        )

    keyboard = build_bank_keyboard(banks, referral_code=user.id)
    bot.send_message(message.chat.id, welcome_text, reply_markup=keyboard)


def is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


def admin_menu_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="📝 Редактировать приветствие", callback_data="admin_welcome"))
    markup.add(types.InlineKeyboardButton(text="🏦 Редактировать банк", callback_data="admin_banks"))
    markup.add(types.InlineKeyboardButton(text="➕ Добавить банк", callback_data="admin_bank_add"))
    markup.add(types.InlineKeyboardButton(text="🗑️ Удалить банк", callback_data="admin_bank_delete"))
    markup.add(types.InlineKeyboardButton(text="🏠 Вернуться в /start", callback_data="goto_start"))
    return markup


def admin_back_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
    return markup


def admin_cancel_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return markup


def start_return_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="🏠 Вернуться в /start", callback_data="goto_start"))
    return markup


def stats_handler(
    message: types.Message,
    bot: telebot.TeleBot,
    db_path: str,
    admin_ids: set[int],
) -> None:
    user = message.from_user
    if not user or not is_admin(user.id, admin_ids):
        bot.send_message(message.chat.id, "🚫 Доступ запрещён.")
        return

    with get_connection(db_path) as conn:
        total_users = count_users(conn)
        top = top_referrers(conn)
        by_bank = referrals_by_bank(conn)

    lines = [f"👥 Всего пользователей: {total_users}", "", "🏆 Топ-10 по приглашениям:"]
    if top:
        for row in top:
            name = row["username"] or row["first_name"] or str(row["tg_id"])
            lines.append(f"• {name}: {row['cnt']}")
    else:
        lines.append("• пока нет данных")

    lines.append("")
    lines.append("🏦 Приглашения по банкам:")
    if by_bank:
        for row in by_bank:
            lines.append(f"• {row['bank_key']}: {row['cnt']}")
    else:
        lines.append("• пока нет данных")

    bot.send_message(message.chat.id, "\n".join(lines))

    if message.text and message.text.lower().strip().endswith("csv"):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["type", "key", "count"])
        for row in top:
            writer.writerow(["top_referrer", row["tg_id"], row["cnt"]])
        for row in by_bank:
            writer.writerow(["bank", row["bank_key"], row["cnt"]])
        buffer.seek(0)
        bot.send_document(
            message.chat.id,
            document=buffer.getvalue().encode("utf-8"),
            visible_file_name="stats.csv",
            caption="📊 CSV статистика",
        )


def configure_proxy() -> None:
    proxy_url = os.environ.get("TELEGRAM_PROXY")
    if proxy_url:
        apihelper.proxy = {
            "http": proxy_url,
            "https": proxy_url,
        }
        logger.info("Using TELEGRAM_PROXY for Telegram API requests")


def main() -> None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("❗ TELEGRAM_TOKEN is not set in .env")

    db_path = os.environ.get("DATABASE_PATH", "bot.sqlite3")
    init_db(db_path, DEFAULT_BANKS)

    admin_ids_raw = os.environ.get("ADMIN_IDS", "")
    admin_ids = {
        int(value)
        for value in admin_ids_raw.replace(" ", "").split(",")
        if value.isdigit()
    }

    configure_proxy()

    with get_connection(db_path) as conn:
        banks = list_banks(conn)
        welcome_text = get_setting(conn, "welcome_text")
        if welcome_text is None:
            env_welcome = os.environ.get("WELCOME_TEXT", DEFAULT_WELCOME_TEXT)
            set_setting(conn, "welcome_text", env_welcome)
            welcome_text = env_welcome

    bot = telebot.TeleBot(token)
    bot.set_my_commands([types.BotCommand("start", "🚀 Запуск и меню")])

    @bot.message_handler(commands=["start"])
    def start_command(message: types.Message) -> None:
        start_handler(message, bot, db_path, banks, welcome_text)

    def send_admin_panel(chat_id: int) -> None:
        bot.send_message(chat_id, "🛠️ Админ-панель:", reply_markup=admin_menu_markup())

    @bot.message_handler(commands=["admin"])
    def admin_command(message: types.Message) -> None:
        user = message.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.send_message(message.chat.id, "🚫 Доступ запрещён.")
            return
        send_admin_panel(message.chat.id)

    @bot.callback_query_handler(func=lambda call: call.data in {"admin_back", "admin_cancel"})
    def admin_back_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.answer_callback_query(call.id, "🚫 Доступ запрещён.")
            return
        bot.answer_callback_query(call.id)
        send_admin_panel(call.message.chat.id)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_welcome")
    def admin_welcome_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.answer_callback_query(call.id, "🚫 Доступ запрещён.")
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(
            call.message.chat.id,
            "✍️ Отправьте новый текст приветствия:",
            reply_markup=admin_cancel_markup(),
        )
        bot.register_next_step_handler(msg, handle_welcome_update)

    def handle_welcome_update(message: types.Message) -> None:
        nonlocal welcome_text
        user = message.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.send_message(message.chat.id, "🚫 Доступ запрещён.")
            return
        new_text = (message.text or "").strip()
        if not new_text:
            bot.send_message(message.chat.id, "⚠️ Текст не может быть пустым.")
            return
        with get_connection(db_path) as conn:
            set_setting(conn, "welcome_text", new_text)
        welcome_text = new_text
        bot.send_message(message.chat.id, "✅ Приветствие обновлено.")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_banks")
    def admin_banks_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.answer_callback_query(call.id, "🚫 Доступ запрещён.")
            return
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        for bank in banks:
            markup.add(
                types.InlineKeyboardButton(
                    text=f"{bank.key}: {bank.base_url}",
                    callback_data=f"bank_edit:{bank.key}",
                )
            )
        markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
        bot.send_message(call.message.chat.id, "🏦 Выберите банк для редактирования:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("bank_edit:"))
    def admin_bank_edit_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.answer_callback_query(call.id, "🚫 Доступ запрещён.")
            return
        bot.answer_callback_query(call.id)
        bank_key = call.data.split(":", 1)[1]
        msg = bot.send_message(
            call.message.chat.id,
            f"🔗 Введите новый base_url для банка {bank_key}:",
            reply_markup=admin_cancel_markup(),
        )
        bot.register_next_step_handler(msg, handle_bank_update, bank_key)

    def handle_bank_update(message: types.Message, bank_key: str) -> None:
        nonlocal banks
        user = message.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.send_message(message.chat.id, "🚫 Доступ запрещён.")
            return
        new_url = (message.text or "").strip()
        if not new_url:
            bot.send_message(message.chat.id, "⚠️ URL не может быть пустым.")
            return
        with get_connection(db_path) as conn:
            update_bank_url(conn, bank_key, new_url)
            banks = list_banks(conn)
        bot.send_message(message.chat.id, f"✅ Ссылка для {bank_key} обновлена.")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_bank_add")
    def admin_bank_add_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.answer_callback_query(call.id, "🚫 Доступ запрещён.")
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(
            call.message.chat.id,
            "➕ Отправьте новый банк в формате `key base_url`:",
            reply_markup=admin_cancel_markup(),
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, handle_bank_add)

    def handle_bank_add(message: types.Message) -> None:
        nonlocal banks
        user = message.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.send_message(message.chat.id, "🚫 Доступ запрещён.")
            return
        text = (message.text or "").strip()
        if not text or " " not in text:
            bot.send_message(message.chat.id, "⚠️ Формат: `key base_url`.", parse_mode="Markdown")
            return
        key, base_url = text.split(maxsplit=1)
        with get_connection(db_path) as conn:
            add_bank(conn, key, base_url)
            banks = list_banks(conn)
        bot.send_message(message.chat.id, f"✅ Банк {key} добавлен.")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_bank_delete")
    def admin_bank_delete_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.answer_callback_query(call.id, "🚫 Доступ запрещён.")
            return
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        for bank in banks:
            markup.add(
                types.InlineKeyboardButton(
                    text=f"🗑️ {bank.key}",
                    callback_data=f"bank_delete:{bank.key}",
                )
            )
        markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
        bot.send_message(call.message.chat.id, "🗑️ Выберите банк для удаления:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("bank_delete:"))
    def admin_bank_delete_confirm(call: types.CallbackQuery) -> None:
        nonlocal banks
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.answer_callback_query(call.id, "🚫 Доступ запрещён.")
            return
        bot.answer_callback_query(call.id)
        bank_key = call.data.split(":", 1)[1]
        with get_connection(db_path) as conn:
            delete_bank(conn, bank_key)
            banks = list_banks(conn)
        bot.send_message(call.message.chat.id, f"✅ Банк {bank_key} удалён.")

    @bot.message_handler(commands=["stats", "admin_stats"])
    def stats_command(message: types.Message) -> None:
        stats_handler(message, bot, db_path, admin_ids)
        bot.send_message(message.chat.id, "📍 Действия:", reply_markup=start_return_markup())

    @bot.callback_query_handler(func=lambda call: call.data == "goto_start")
    def goto_start_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user:
            return
        bot.answer_callback_query(call.id)
        start_handler(call.message, bot, db_path, banks, welcome_text)

    logger.info("🤖 Bot started with polling")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
