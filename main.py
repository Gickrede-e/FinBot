import csv
import io
import logging
import os
from typing import Optional, Tuple

import telebot
from telebot import types

from models import (
    DEFAULT_BANKS,
    Bank,
    count_users,
    create_referral,
    ensure_user,
    get_connection,
    get_user_id,
    has_referral,
    init_db,
    list_banks,
    referrals_by_bank,
    top_referrers,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Привет! Это реферальный бот. Выберите банк ниже, чтобы получить свою ссылку."
)


def parse_payload(payload: str) -> Optional[Tuple[int, str]]:
    """
    Expected format: ref_{referrer_id}_{bank_key}
    """
    if not payload:
        return None
    parts = payload.split("_")
    if len(parts) != 3 or parts[0] != "ref":
        return None
    referrer_part, bank_key = parts[1], parts[2]
    if not referrer_part.isdigit():
        return None
    return int(referrer_part), bank_key


def build_bank_keyboard(banks: list[Bank], referral_code: int) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for bank in banks:
        url = f"{bank.base_url}?ref={referral_code}"
        keyboard.add(types.InlineKeyboardButton(text=bank.key, url=url))
    return keyboard


def start_handler(message: types.Message, bot: telebot.TeleBot, db_path: str) -> None:
    payload = ""
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            payload = parts[1].strip()

    user = message.from_user
    if user is None:
        return

    with get_connection(db_path) as conn:
        user_id = ensure_user(
            conn,
            user.id,
            user.username,
            user.first_name,
            user.last_name,
        )
        invite_result = None
        parsed = parse_payload(payload)
        if parsed:
            referrer_tg_id, bank_key = parsed
            referrer_id = get_user_id(conn, referrer_tg_id)
            if referrer_id and referrer_id != user_id and not has_referral(conn, user_id):
                valid_bank_keys = {bank.key for bank in list_banks(conn)}
                if bank_key in valid_bank_keys:
                    create_referral(conn, referrer_id, user_id, bank_key)
                    invite_result = bank_key

    if invite_result:
        bot.send_message(
            message.chat.id,
            f"Спасибо! Вас пригласили по реферальной ссылке банка {invite_result}.",
        )

    with get_connection(db_path) as conn:
        banks = list_banks(conn)
    keyboard = build_bank_keyboard(banks, referral_code=user.id)
    bot.send_message(message.chat.id, WELCOME_TEXT, reply_markup=keyboard)


def stats_handler(message: types.Message, bot: telebot.TeleBot, db_path: str, admin_id: Optional[int]) -> None:
    user = message.from_user
    if not user or admin_id is None or user.id != admin_id:
        bot.send_message(message.chat.id, "Доступ запрещён.")
        return

    with get_connection(db_path) as conn:
        total_users = count_users(conn)
        top = top_referrers(conn)
        by_bank = referrals_by_bank(conn)

    lines = [f"Всего пользователей: {total_users}", "", "Топ-10 по приглашениям:"]
    if top:
        for row in top:
            name = row["username"] or row["first_name"] or str(row["tg_id"])
            lines.append(f"- {name}: {row['cnt']}")
    else:
        lines.append("- пока нет данных")

    lines.append("")
    lines.append("Приглашения по банкам:")
    if by_bank:
        for row in by_bank:
            lines.append(f"- {row['bank_key']}: {row['cnt']}")
    else:
        lines.append("- пока нет данных")

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
            caption="CSV статистика",
        )


def main() -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not set")

    db_path = os.environ.get("DATABASE_PATH", "bot.sqlite3")
    init_db(db_path, DEFAULT_BANKS)

    admin_id_raw = os.environ.get("ADMIN_ID")
    admin_id = int(admin_id_raw) if admin_id_raw and admin_id_raw.isdigit() else None

    bot = telebot.TeleBot(token)

    @bot.message_handler(commands=["start"])
    def start_command(message: types.Message) -> None:
        start_handler(message, bot, db_path)

    @bot.message_handler(commands=["stats", "admin_stats"])
    def stats_command(message: types.Message) -> None:
        stats_handler(message, bot, db_path, admin_id)

    logger.info("Bot started with polling")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
