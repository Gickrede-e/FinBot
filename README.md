# FinBot — реферальный Telegram-бот (pyTelegramBotAPI)

## Возможности
- Регистрация пользователей через `/start`.
- Админская статистика `/stats` (или `/admin_stats`).
- Админ-панель `/admin` для редактирования приветствия и банковских ссылок.
- Добавление и удаление банков из админ-панели.
- Запрос вознаграждения после регистрации карты (телефон, имя, фамилия).
- SQLite хранение в одном файле.

## Требования
- Python 3.10+
- Настройки в `.env`:
  - `TELEGRAM_TOKEN` — токен бота (не хранится в коде)
  - `DATABASE_PATH` — путь к SQLite файлу (по умолчанию `bot.sqlite3`)
  - `ADMIN_IDS` — Telegram ID админов через запятую (например, `123,456`) для `/stats` и `/admin`
  - `TELEGRAM_PROXY` — опционально, proxy URL для доступа к Telegram API (например, `http://user:pass@host:port`)

## Где редактировать ссылки банков
Базовые URL можно менять через `/admin`. URL должен быть валидным с `http://` или `https://`. Исходные значения находятся в `models.py` в `DEFAULT_BANKS`.

## Ошибка ProxyError при polling
Если при запуске видите ошибку вида `ProxyError` или `Remote end closed connection without response`,
значит доступ к `api.telegram.org` блокируется прокси/фаерволом. Укажите прокси через `TELEGRAM_PROXY`:
Отредактируйте `.env` и добавьте строку:
```
TELEGRAM_PROXY="http://user:pass@host:port"
```
После этого бот будет использовать прокси для всех запросов к Telegram API.
