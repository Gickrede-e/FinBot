import asyncio
import csv
import io
import logging
import os
from typing import Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from models import (
    DEFAULT_BANKS,
    Bank,
    count_users,
    create_referral,
    get_connection,
    get_user_id,
    has_referral,
    init_db,
    list_banks,
    referrals_by_bank,
    top_referrers,
    ensure_user,
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


def build_bank_keyboard(banks: list[Bank], referral_code: int) -> InlineKeyboardMarkup:
    rows = []
    for bank in banks:
        url = f"{bank.base_url}?ref={referral_code}"
        rows.append([InlineKeyboardButton(text=bank.key, url=url)])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_path = context.application.bot_data["db_path"]
    payload = context.args[0] if context.args else ""
    user = update.effective_user
    if user is None:
        return

    def db_task() -> Tuple[int, Optional[str]]:
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
            return user_id, invite_result

    user_id, invite_result = await asyncio.to_thread(db_task)

    if invite_result:
        await update.message.reply_text(
            f"Спасибо! Вас пригласили по реферальной ссылке банка {invite_result}."
        )

    def load_banks() -> list[Bank]:
        with get_connection(db_path) as conn:
            return list_banks(conn)

    banks = await asyncio.to_thread(load_banks)
    keyboard = build_bank_keyboard(banks, referral_code=user.id)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=keyboard)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = context.application.bot_data.get("admin_id")
    user = update.effective_user
    if not user or admin_id is None or user.id != admin_id:
        await update.message.reply_text("Доступ запрещён.")
        return

    db_path = context.application.bot_data["db_path"]

    def stats_task():
        with get_connection(db_path) as conn:
            total_users = count_users(conn)
            top = top_referrers(conn)
            by_bank = referrals_by_bank(conn)
        return total_users, top, by_bank

    total_users, top, by_bank = await asyncio.to_thread(stats_task)

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

    await update.message.reply_text("\n".join(lines))

    if context.args and context.args[0].lower() == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["type", "key", "count"])
        for row in top:
            writer.writerow(["top_referrer", row["tg_id"], row["cnt"]])
        for row in by_bank:
            writer.writerow(["bank", row["bank_key"], row["cnt"]])
        buffer.seek(0)
        await update.message.reply_document(
            document=buffer.getvalue().encode("utf-8"),
            filename="stats.csv",
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

    application = Application.builder().token(token).build()
    application.bot_data["db_path"] = db_path
    application.bot_data["admin_id"] = admin_id

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("admin_stats", stats))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
