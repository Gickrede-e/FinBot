import os

from models import DEFAULT_BANKS, init_db


def main() -> None:
    db_path = os.environ.get("DATABASE_PATH", "bot.sqlite3")
    init_db(db_path, DEFAULT_BANKS)
    print(f"Database initialized at {db_path}")


if __name__ == "__main__":
    main()
