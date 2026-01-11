from models import DEFAULT_BANKS, init_db


def main() -> None:
    init_db(DEFAULT_BANKS)
    print("Database initialized")


if __name__ == "__main__":
    main()
