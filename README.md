# FinBot — реферальный Telegram-бот (python-telegram-bot v20)

## Возможности
- Регистрация пользователей через `/start`.
- Учёт приглашений по deep-link формату `start=ref_{referrer_id}_{bank_key}`.
- Кнопки для банков с реферальными URL на основе кода пользователя.
- Админская статистика `/stats` (или `/admin_stats`).
- SQLite хранение в одном файле.

## Требования
- Python 3.10+
- Переменные окружения:
  - `TELEGRAM_TOKEN` — токен бота (не хранится в коде)
  - `DATABASE_PATH` — путь к SQLite файлу (по умолчанию `bot.sqlite3`)
  - `ADMIN_ID` — Telegram ID администратора (для `/stats`)

## Установка и запуск
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_TOKEN="<ваш токен>"
export DATABASE_PATH="bot.sqlite3"
export ADMIN_ID="123456789"
python init_db.py
python main.py
```

## Схема БД (SQLite)
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER NOT NULL,
    referred_id INTEGER UNIQUE NOT NULL,
    bank_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(referrer_id) REFERENCES users(id),
    FOREIGN KEY(referred_id) REFERENCES users(id)
);

CREATE TABLE banks (
    key TEXT PRIMARY KEY,
    base_url TEXT NOT NULL
);
```

## Как работают реферальные ссылки
### Внешние банковские ссылки
Каждому пользователю показываются кнопки вида:
```
{bank_base_url}?ref={telegram_id}
```
Кодом приглашения служит Telegram ID пользователя. Это позволяет банку отследить, кто пригласил.

### Deep-link для приглашений в бота
Используйте формат:
```
https://t.me/<bot_username>?start=ref_{referrer_id}_{bank_key}
```
Пример:
```
https://t.me/MyFinBot?start=ref_123456789_alfa
```
При первом `/start` бот запишет, что пользователь пришёл по реферальной ссылке `referrer_id` и `bank_key`.

## Статистика
- `/stats` — доступно только `ADMIN_ID`.
- Для CSV можно выполнить `/stats csv`.

## Безопасность payload (опционально)
Сейчас payload проверяется по формату `ref_{referrer_id}_{bank_key}`. Для защиты от подделок можно внедрить HMAC-подпись:
```
ref_{referrer_id}_{bank_key}_{signature}
```
Где `signature = HMAC(secret, f"{referrer_id}:{bank_key}")`.
На стороне бота сверяйте подпись перед записью приглашения.

## Тестирование
1. Эмуляция приглашения:
   - Зайдите по ссылке `https://t.me/<bot_username>?start=ref_<your_id>_alfa`.
2. Статистика:
   - `/stats` или `/stats csv`.

## Где редактировать ссылки банков
Список банков и базовые URL находятся в `models.py` в `DEFAULT_BANKS`. Замените placeholders на реальные ссылки.
