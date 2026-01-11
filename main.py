import csv
import io
import logging
import os
from urllib.parse import urlparse
from typing import Optional

import telebot
from dotenv import load_dotenv
from telebot import apihelper, types

from models import (
    DEFAULT_BANKS,
    Bank,
    add_bank,
    count_users,
    count_reward_requests_by_status,
    create_reward_request,
    delete_bank,
    ensure_user,
    get_reward_request,
    get_connection,
    get_setting,
    has_pending_reward_request,
    init_db,
    list_banks,
    list_reward_history,
    list_reward_requests,
    referrals_by_bank,
    set_setting,
    top_referrers,
    update_reward_request_status,
    update_bank_url,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_WELCOME_TEXT = (
    "👋 Привет! Это реферальный бот. Выберите банк ниже, чтобы получить свою ссылку."
)
DEFAULT_PAYOUT_SCHEME_TEXT = "ℹ️ Здесь будет описание схемы выплат."


def normalize_bank_url(base_url: str) -> Optional[str]:
    parsed = urlparse(base_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return base_url
    candidate = f"https://{base_url}"
    parsed_candidate = urlparse(candidate)
    if parsed_candidate.scheme in {"http", "https"} and parsed_candidate.netloc:
        return candidate
    return None


def build_bank_keyboard(
    banks: list[Bank], referral_code: int, is_admin_user: bool
) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for bank in banks:
        normalized = normalize_bank_url(bank.base_url)
        if not normalized:
            logger.warning("Invalid bank URL for %s: %s", bank.key, bank.base_url)
            continue
        url = f"{normalized}?ref={referral_code}"
        keyboard.add(types.InlineKeyboardButton(text=bank.key, url=url))
    keyboard.add(types.InlineKeyboardButton(text="🧾 Схема выплат", callback_data="payout_scheme"))
    keyboard.add(
        types.InlineKeyboardButton(
            text="🎁 Отправить запрос на вознаграждение",
            callback_data="reward_request",
        )
    )
    if is_admin_user:
        keyboard.add(
            types.InlineKeyboardButton(text="📊 Статистика", callback_data="goto_stats"),
            types.InlineKeyboardButton(text="🛠️ Админ-панель", callback_data="goto_admin"),
        )
    return keyboard


def edit_or_send(
    bot: telebot.TeleBot,
    message: types.Message,
    text: str,
    reply_markup: Optional[types.InlineKeyboardMarkup] = None,
) -> None:
    if message and message.chat:
        try:
            bot.edit_message_text(
                text=text,
                chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            bot.send_message(message.chat.id, text, reply_markup=reply_markup)


def answer_callback(bot: telebot.TeleBot, call: types.CallbackQuery, text: Optional[str] = None) -> None:
    try:
        bot.answer_callback_query(call.id, text=text)
    except Exception:
        logger.warning("Failed to answer callback query", exc_info=True)


def start_handler(
    message: types.Message,
    bot: telebot.TeleBot,
    banks: list[Bank],
    welcome_text: str,
    is_admin_user: bool,
) -> None:
    user = message.from_user
    if user is None:
        return

    with get_connection() as conn:
        ensure_user(
            conn,
            user.id,
            user.username,
            user.first_name,
            user.last_name,
        )

    keyboard = build_bank_keyboard(banks, referral_code=user.id, is_admin_user=is_admin_user)
    edit_or_send(bot, message, welcome_text, reply_markup=keyboard)


def is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


def admin_menu_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="📝 Редактировать приветствие", callback_data="admin_welcome"))
    markup.add(
        types.InlineKeyboardButton(
            text="🧾 Редактировать схему выплат",
            callback_data="admin_payout_scheme",
        )
    )
    markup.add(types.InlineKeyboardButton(text="🏦 Редактировать банк", callback_data="admin_banks"))
    markup.add(types.InlineKeyboardButton(text="➕ Добавить банк", callback_data="admin_bank_add"))
    markup.add(types.InlineKeyboardButton(text="🗑️ Удалить банк", callback_data="admin_bank_delete"))
    markup.add(types.InlineKeyboardButton(text="📋 Запросы на вознаграждение", callback_data="admin_reward_requests"))
    markup.add(types.InlineKeyboardButton(text="🗂️ История вознаграждений", callback_data="admin_reward_history"))
    markup.add(types.InlineKeyboardButton(text="🏠 Вернуться в /start", callback_data="goto_start"))
    return markup


def admin_cancel_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return markup


def reward_cancel_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="❌ Отмена", callback_data="reward_cancel"))
    return markup


def build_stats_text(total_users: int, counts: dict[str, int]) -> str:
    return (
        "📊 Статистика\n"
        f"👥 Пользователей: {total_users}\n"
        f"✅ Принятых заявок: {counts.get('approved', 0)}\n"
        f"❌ Отклонённых заявок: {counts.get('rejected', 0)}\n"
        f"⏳ Pending заявок: {counts.get('pending', 0)}"
    )


def stats_menu_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(text="🗂️ История вознаграждений", callback_data="admin_reward_history")
    )
    markup.add(
        types.InlineKeyboardButton(text="📋 Запросы на вознаграждение", callback_data="admin_reward_requests")
    )
    markup.add(types.InlineKeyboardButton(text="🏠 Вернуться в /start", callback_data="goto_start"))
    return markup


def stats_handler(
    message: types.Message,
    bot: telebot.TeleBot,
    admin_ids: set[int],
    reply_markup: Optional[types.InlineKeyboardMarkup] = None,
    user_id: Optional[int] = None,
) -> None:
    resolved_user_id = user_id or (message.from_user.id if message.from_user else None)
    if not resolved_user_id or not is_admin(resolved_user_id, admin_ids):
        edit_or_send(bot, message, "🚫 Доступ запрещён.")
        return

    with get_connection() as conn:
        total_users = count_users(conn)
        counts = count_reward_requests_by_status(conn)

    text = build_stats_text(total_users, counts)
    edit_or_send(bot, message, text, reply_markup=reply_markup or stats_menu_markup())

    if message.text and message.text.lower().strip().endswith("csv"):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["metric", "count"])
        writer.writerow(["users", total_users])
        writer.writerow(["approved", counts.get("approved", 0)])
        writer.writerow(["rejected", counts.get("rejected", 0)])
        writer.writerow(["pending", counts.get("pending", 0)])
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

    init_db(DEFAULT_BANKS)

    admin_ids_raw = os.environ.get("ADMIN_IDS", "")
    admin_ids = {
        int(value)
        for value in admin_ids_raw.replace(" ", "").split(",")
        if value.isdigit()
    }

    configure_proxy()

    with get_connection() as conn:
        banks = list_banks(conn)
        welcome_text = get_setting(conn, "welcome_text")
        if welcome_text is None:
            env_welcome = os.environ.get("WELCOME_TEXT", DEFAULT_WELCOME_TEXT)
            set_setting(conn, "welcome_text", env_welcome)
            welcome_text = env_welcome
        payout_scheme_text = get_setting(conn, "payout_scheme_text")
        if payout_scheme_text is None:
            env_payout_scheme = os.environ.get(
                "PAYOUT_SCHEME_TEXT", DEFAULT_PAYOUT_SCHEME_TEXT
            )
            set_setting(conn, "payout_scheme_text", env_payout_scheme)
            payout_scheme_text = env_payout_scheme

    bot = telebot.TeleBot(token)
    bot.set_my_commands([types.BotCommand("start", "🚀 Запуск и меню")])

    admin_menu = admin_menu_markup()
    admin_cancel = admin_cancel_markup()
    reward_cancel = reward_cancel_markup()

    @bot.message_handler(commands=["start"])
    def start_command(message: types.Message) -> None:
        is_admin_user = message.from_user is not None and is_admin(
            message.from_user.id, admin_ids
        )
        start_handler(message, bot, banks, welcome_text, is_admin_user)

    def send_admin_panel(chat_id: int, message: Optional[types.Message] = None) -> None:
        if message:
            edit_or_send(bot, message, "🛠️ Админ-панель:", reply_markup=admin_menu)
            return
        bot.send_message(chat_id, "🛠️ Админ-панель:", reply_markup=admin_menu)

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
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        if call.data == "admin_cancel":
            bot.clear_step_handler_by_chat_id(call.message.chat.id)
        send_admin_panel(call.message.chat.id, call.message)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_welcome")
    def admin_welcome_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        msg = bot.send_message(
            call.message.chat.id,
            "✍️ Отправьте новый текст приветствия:",
            reply_markup=admin_cancel,
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
        with get_connection() as conn:
            set_setting(conn, "welcome_text", new_text)
        welcome_text = new_text
        bot.send_message(message.chat.id, "✅ Приветствие обновлено.")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_payout_scheme")
    def admin_payout_scheme_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        msg = bot.send_message(
            call.message.chat.id,
            "✍️ Отправьте новый текст схемы выплат:",
            reply_markup=admin_cancel,
        )
        bot.register_next_step_handler(msg, handle_payout_scheme_update)

    def handle_payout_scheme_update(message: types.Message) -> None:
        nonlocal payout_scheme_text
        user = message.from_user
        if not user or not is_admin(user.id, admin_ids):
            bot.send_message(message.chat.id, "🚫 Доступ запрещён.")
            return
        new_text = (message.text or "").strip()
        if not new_text:
            bot.send_message(message.chat.id, "⚠️ Текст не может быть пустым.")
            return
        with get_connection() as conn:
            set_setting(conn, "payout_scheme_text", new_text)
        payout_scheme_text = new_text
        bot.send_message(message.chat.id, "✅ Схема выплат обновлена.")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_banks")
    def admin_banks_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        markup = types.InlineKeyboardMarkup()
        for bank in banks:
            markup.add(
                types.InlineKeyboardButton(
                    text=f"{bank.key}: {bank.base_url}",
                    callback_data=f"bank_edit:{bank.key}",
                )
            )
        markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
        edit_or_send(bot, call.message, "🏦 Выберите банк для редактирования:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("bank_edit:"))
    def admin_bank_edit_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        bank_key = call.data.split(":", 1)[1]
        msg = bot.send_message(
            call.message.chat.id,
            f"🔗 Введите новый base_url для банка {bank_key}:",
            reply_markup=admin_cancel,
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
        if not normalize_bank_url(new_url):
            bot.send_message(message.chat.id, "⚠️ URL должен быть валидным (http/https).")
            return
        with get_connection() as conn:
            update_bank_url(conn, bank_key, new_url)
            banks = list_banks(conn)
        bot.send_message(message.chat.id, f"✅ Ссылка для {bank_key} обновлена.")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_bank_add")
    def admin_bank_add_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        msg = bot.send_message(
            call.message.chat.id,
            "➕ Отправьте новый банк в формате `название | base_url`:",
            reply_markup=admin_cancel,
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
        if "|" not in text:
            bot.send_message(
                message.chat.id,
                "⚠️ Формат: `название | base_url`.",
                parse_mode="Markdown",
            )
            return
        key, base_url = [part.strip() for part in text.split("|", 1)]
        if not key or not base_url:
            bot.send_message(
                message.chat.id,
                "⚠️ Формат: `название | base_url`.",
                parse_mode="Markdown",
            )
            return
        if not normalize_bank_url(base_url):
            bot.send_message(message.chat.id, "⚠️ URL должен быть валидным (http/https).")
            return
        with get_connection() as conn:
            added = add_bank(conn, key, base_url)
            if added:
                banks = list_banks(conn)
        if added:
            bot.send_message(message.chat.id, f"✅ Банк {key} добавлен.")
        else:
            bot.send_message(message.chat.id, f"⚠️ Банк с ключом {key} уже существует.")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_bank_delete")
    def admin_bank_delete_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        markup = types.InlineKeyboardMarkup()
        for bank in banks:
            markup.add(
                types.InlineKeyboardButton(
                    text=f"🗑️ {bank.key}",
                    callback_data=f"bank_delete:{bank.key}",
                )
            )
        markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
        edit_or_send(bot, call.message, "🗑️ Выберите банк для удаления:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_reward_requests")
    def admin_reward_requests_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        with get_connection() as conn:
            rows = list_reward_requests(conn)
        if not rows:
            back_markup = types.InlineKeyboardMarkup()
            back_markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
            edit_or_send(bot, call.message, "📭 Запросов пока нет.", reply_markup=back_markup)
            return
        markup = types.InlineKeyboardMarkup()
        for row in rows:
            display_name = " ".join(
                part for part in [row["tg_first_name"], row["tg_last_name"]] if part
            ) or str(row["tg_id"])
            label = f"#{row['id']} • {display_name} • {row['status']}"
            markup.add(
                types.InlineKeyboardButton(
                    text=label,
                    callback_data=f"reward_view:{row['id']}",
                )
            )
        markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
        edit_or_send(bot, call.message, "📋 Запросы на вознаграждение:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_reward_history")
    def admin_reward_history_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        with get_connection() as conn:
            rows = list_reward_history(conn)
        if not rows:
            back_markup = types.InlineKeyboardMarkup()
            back_markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
            edit_or_send(bot, call.message, "📭 История пока пуста.", reply_markup=back_markup)
            return
        markup = types.InlineKeyboardMarkup()
        for row in rows:
            display_name = " ".join(
                part for part in [row["tg_first_name"], row["tg_last_name"]] if part
            ) or str(row["tg_id"])
            label = f"#{row['id']} • {display_name} • {row['status']}"
            markup.add(
                types.InlineKeyboardButton(
                    text=label,
                    callback_data=f"reward_view:{row['id']}",
                )
            )
        markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
        edit_or_send(bot, call.message, "🗂️ История вознаграждений:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("reward_view:"))
    def reward_view_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        request_id = int(call.data.split(":", 1)[1])
        with get_connection() as conn:
            row = get_reward_request(conn, request_id)
        if not row:
            bot.send_message(call.message.chat.id, "⚠️ Запрос не найден.")
            return
        display_name = " ".join(
            part for part in [row["tg_first_name"], row["tg_last_name"]] if part
        ) or str(row["tg_id"])
        username_line = f"• Username: @{row['username']}" if row["username"] else "• Username: —"
        message = (
            "🎁 Запрос на вознаграждение\n"
            f"• Request ID: {row['id']}\n"
            f"• TG ID: {row['tg_id']}\n"
            f"• Display: {display_name}\n"
            f"{username_line}\n"
            f"• Банк: {row['bank_key']}\n"
            f"• Телефон: {row['phone']}\n"
            f"• Имя: {row['first_name']}\n"
            f"• Фамилия: {row['last_name']}\n"
            f"• Статус: {row['status']}\n"
            f"• Создан: {row['created_at']}"
        )
        action_markup = types.InlineKeyboardMarkup()
        if row["status"] == "pending":
            action_markup.add(
                types.InlineKeyboardButton(
                    text="✅ Принять", callback_data=f"reward_set:{row['id']}:approved"
                ),
                types.InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"reward_set:{row['id']}:rejected"
                ),
            )
            action_markup.add(
                types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_reward_requests")
            )
        else:
            action_markup.add(
                types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_reward_history")
            )
        edit_or_send(bot, call.message, message, reply_markup=action_markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("reward_set:"))
    def reward_set_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        _, request_id, status = call.data.split(":", 2)
        with get_connection() as conn:
            request_row = get_reward_request(conn, int(request_id))
            update_reward_request_status(conn, int(request_id), status)
        status_label = "принят" if status == "approved" else "отклонён"
        edit_or_send(
            bot,
            call.message,
            f"✅ Статус запроса {request_id}: {status_label}.",
            reply_markup=stats_menu_markup(),
        )
        if request_row:
            user_message = (
                "✅ Ваш запрос на вознаграждение принят."
                if status == "approved"
                else "❌ Ваш запрос на вознаграждение отклонён."
            )
            bot.send_message(request_row["tg_id"], user_message)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("bank_delete:"))
    def admin_bank_delete_confirm(call: types.CallbackQuery) -> None:
        nonlocal banks
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        bank_key = call.data.split(":", 1)[1]
        with get_connection() as conn:
            delete_bank(conn, bank_key)
            banks = list_banks(conn)
        bot.send_message(call.message.chat.id, f"✅ Банк {bank_key} удалён.")

    @bot.message_handler(commands=["stats", "admin_stats"])
    def stats_command(message: types.Message) -> None:
        stats_handler(message, bot, admin_ids)

    @bot.callback_query_handler(func=lambda call: call.data == "reward_request")
    def reward_request_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user:
            return
        answer_callback(bot, call)
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
        with get_connection() as conn:
            user_id = ensure_user(
                conn,
                user.id,
                user.username,
                user.first_name,
                user.last_name,
            )
            if has_pending_reward_request(conn, user_id):
                bot.send_message(
                    call.message.chat.id,
                    "⏳ У вас уже есть запрос в обработке.",
                )
                return
        markup = types.InlineKeyboardMarkup()
        for bank in banks:
            markup.add(
                types.InlineKeyboardButton(
                    text=f"🏦 {bank.key}",
                    callback_data=f"reward_bank:{bank.key}",
                )
            )
        markup.add(types.InlineKeyboardButton(text="❌ Отмена", callback_data="reward_cancel"))
        edit_or_send(
            bot,
            call.message,
            "🏦 Выберите банк для запроса вознаграждения:",
            reply_markup=markup,
        )

    @bot.callback_query_handler(func=lambda call: call.data == "payout_scheme")
    def payout_scheme_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user:
            return
        answer_callback(bot, call)
        back_markup = types.InlineKeyboardMarkup()
        back_markup.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="goto_start"))
        edit_or_send(bot, call.message, payout_scheme_text, reply_markup=back_markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("reward_bank:"))
    def reward_bank_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user:
            return
        answer_callback(bot, call)
        bank_key = call.data.split(":", 1)[1]
        msg = bot.send_message(
            call.message.chat.id,
            "📱 Укажите номер телефона (например, +79991234567):",
            reply_markup=reward_cancel,
        )
        bot.register_next_step_handler(msg, handle_reward_phone, bank_key)

    def handle_reward_phone(message: types.Message, bank_key: str) -> None:
        user = message.from_user
        if not user:
            return
        phone = (message.text or "").strip()
        if not phone.startswith("+") or len(phone) < 10:
            msg = bot.send_message(
                message.chat.id,
                "⚠️ Укажите телефон в формате +79991234567.",
                reply_markup=reward_cancel,
            )
            bot.clear_step_handler_by_chat_id(message.chat.id)
            bot.register_next_step_handler(msg, handle_reward_phone, bank_key)
            return
        msg = bot.send_message(message.chat.id, "🧑 Укажите имя:", reply_markup=reward_cancel)
        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(msg, handle_reward_first_name, bank_key, phone)

    def handle_reward_first_name(message: types.Message, bank_key: str, phone: str) -> None:
        user = message.from_user
        if not user:
            return
        first_name = (message.text or "").strip()
        if not first_name:
            msg = bot.send_message(
                message.chat.id,
                "⚠️ Имя не может быть пустым.",
                reply_markup=reward_cancel,
            )
            bot.clear_step_handler_by_chat_id(message.chat.id)
            bot.register_next_step_handler(msg, handle_reward_first_name, bank_key, phone)
            return
        msg = bot.send_message(message.chat.id, "🧾 Укажите фамилию:", reply_markup=reward_cancel)
        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(msg, handle_reward_last_name, bank_key, phone, first_name)

    def handle_reward_last_name(message: types.Message, bank_key: str, phone: str, first_name: str) -> None:
        user = message.from_user
        if not user:
            return
        last_name = (message.text or "").strip()
        if not last_name:
            msg = bot.send_message(
                message.chat.id,
                "⚠️ Фамилия не может быть пустой.",
                reply_markup=reward_cancel,
            )
            bot.clear_step_handler_by_chat_id(message.chat.id)
            bot.register_next_step_handler(
                msg, handle_reward_last_name, bank_key, phone, first_name
            )
            return
        with get_connection() as conn:
            user_id = ensure_user(
                conn,
                user.id,
                user.username,
                user.first_name,
                user.last_name,
            )
            if has_pending_reward_request(conn, user_id):
                bot.send_message(message.chat.id, "⏳ У вас уже есть запрос в обработке.")
                return
            create_reward_request(conn, user_id, bank_key, phone, first_name, last_name)
        edit_or_send(bot, message, "✅ Запрос отправлен. Мы свяжемся с вами.")
        is_admin_user = message.from_user is not None and is_admin(
            message.from_user.id, admin_ids
        )
        start_handler(message, bot, banks, welcome_text, is_admin_user)

    @bot.callback_query_handler(func=lambda call: call.data == "reward_cancel")
    def reward_cancel_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user:
            return
        answer_callback(bot, call)
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
        is_admin_user = call.from_user is not None and is_admin(
            call.from_user.id, admin_ids
        )
        start_handler(call.message, bot, banks, welcome_text, is_admin_user)

    @bot.callback_query_handler(func=lambda call: call.data == "goto_start")
    def goto_start_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user:
            return
        answer_callback(bot, call)
        is_admin_user = call.from_user is not None and is_admin(
            call.from_user.id, admin_ids
        )
        start_handler(call.message, bot, banks, welcome_text, is_admin_user)

    @bot.callback_query_handler(func=lambda call: call.data == "goto_admin")
    def goto_admin_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        send_admin_panel(call.message.chat.id, call.message)

    @bot.callback_query_handler(func=lambda call: call.data == "goto_stats")
    def goto_stats_callback(call: types.CallbackQuery) -> None:
        user = call.from_user
        if not user or not is_admin(user.id, admin_ids):
            answer_callback(bot, call, "🚫 Доступ запрещён.")
            return
        answer_callback(bot, call)
        stats_handler(
            call.message,
            bot,
            admin_ids,
            user_id=user.id,
        )

    logger.info("🤖 Bot started with polling")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
