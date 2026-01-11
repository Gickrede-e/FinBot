from models import DEFAULT_BANKS, init_db


def resolve_db_path() -> str:
    env_path = os.environ.get("DATABASE_PATH")
    if env_path:
        return env_path
    data_dir = "/data"
    if os.path.isdir(data_dir) and os.access(data_dir, os.W_OK):
        return os.path.join(data_dir, "bot.sqlite3")
    return "bot.sqlite3"


def main() -> None:
    init_db(DEFAULT_BANKS)
    print("Database initialized")


if __name__ == "__main__":
    main()
