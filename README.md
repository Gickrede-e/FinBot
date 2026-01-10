# FinBot — реферальный Telegram-бот (pyTelegramBotAPI)

## Возможности
- Регистрация пользователей через `/start`.
- Кнопки для банков с реферальными URL на основе кода пользователя.
- Админская статистика `/stats` (или `/admin_stats`).
- Админ-панель `/admin` для редактирования приветствия и банковских ссылок.
- Добавление и удаление банков из админ-панели.
- SQLite хранение в одном файле.

## Требования
- Python 3.10+
- Настройки в `.env`:
  - `TELEGRAM_TOKEN` — токен бота (не хранится в коде)
  - `DATABASE_PATH` — путь к SQLite файлу (по умолчанию `bot.sqlite3`)
  - `ADMIN_IDS` — Telegram ID админов через запятую (например, `123,456`) для `/stats` и `/admin`
  - `TELEGRAM_PROXY` — опционально, proxy URL для доступа к Telegram API (например, `http://user:pass@host:port`)

## Установка и запуск
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# затем отредактируйте .env
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

## Статистика
- `/stats` — доступно только `ADMIN_IDS`.
- Для CSV можно выполнить `/stats csv`.

## Админ-панель
Команда `/admin` (доступна только `ADMIN_IDS`) открывает меню:
- редактирование приветственного текста;
- редактирование базовых URL реферальных ссылок банков;
- добавление и удаление банков.
В админ-панели доступны кнопки **Назад** и **Отмена**, чтобы прервать редактирование и вернуться к меню.

## Тестирование
1. Статистика:
   - `/stats` или `/stats csv`.

## Где редактировать ссылки банков
Базовые URL можно менять через `/admin`. Исходные значения находятся в `models.py` в `DEFAULT_BANKS`.

## Ошибка ProxyError при polling
Если при запуске видите ошибку вида `ProxyError` или `Remote end closed connection without response`,
значит доступ к `api.telegram.org` блокируется прокси/фаерволом. Укажите прокси через `TELEGRAM_PROXY`:
Отредактируйте `.env` и добавьте строку:
```
TELEGRAM_PROXY="http://user:pass@host:port"
```
После этого бот будет использовать прокси для всех запросов к Telegram API.
