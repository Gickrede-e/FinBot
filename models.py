import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional


@dataclass(frozen=True)
class Bank:
    key: str
    base_url: str


DEFAULT_BANKS = [
    Bank(key="alfa", base_url="https://example.com/alfa"),
    Bank(key="tbank", base_url="https://example.com/tbank"),
    Bank(key="gazprom", base_url="https://example.com/gazprom"),
]


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER NOT NULL,
    referred_id INTEGER UNIQUE NOT NULL,
    bank_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(referrer_id) REFERENCES users(id),
    FOREIGN KEY(referred_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS banks (
    key TEXT PRIMARY KEY,
    base_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str, banks: Iterable[Bank]) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO banks (key, base_url) VALUES (?, ?)",
            [(bank.key, bank.base_url) for bank in banks],
        )


def ensure_user(
    conn: sqlite3.Connection,
    tg_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
) -> int:
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO users (tg_id, username, first_name, last_name, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (tg_id, username, first_name, last_name, now),
    )
    row = conn.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    return int(row["id"])


def get_user_id(conn: sqlite3.Connection, tg_id: int) -> Optional[int]:
    row = conn.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    if not row:
        return None
    return int(row["id"])


def has_referral(conn: sqlite3.Connection, referred_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM referrals WHERE referred_id = ?", (referred_id,)
    ).fetchone()
    return row is not None


def create_referral(
    conn: sqlite3.Connection,
    referrer_id: int,
    referred_id: int,
    bank_key: str,
) -> None:
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bank_key, created_at)"
        " VALUES (?, ?, ?, ?)",
        (referrer_id, referred_id, bank_key, now),
    )


def list_banks(conn: sqlite3.Connection) -> list[Bank]:
    rows = conn.execute("SELECT key, base_url FROM banks ORDER BY key").fetchall()
    return [Bank(key=row["key"], base_url=row["base_url"]) for row in rows]


def add_bank(conn: sqlite3.Connection, key: str, base_url: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO banks (key, base_url) VALUES (?, ?)",
        (key, base_url),
    )


def update_bank_url(conn: sqlite3.Connection, key: str, base_url: str) -> None:
    conn.execute(
        "UPDATE banks SET base_url = ? WHERE key = ?",
        (base_url, key),
    )


def delete_bank(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM banks WHERE key = ?", (key,))


def get_setting(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    return str(row["value"])


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )


def count_users(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
    return int(row["cnt"])


def top_referrers(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT u.tg_id, u.username, u.first_name, u.last_name, COUNT(r.id) AS cnt
        FROM users u
        JOIN referrals r ON r.referrer_id = u.id
        GROUP BY u.id
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def referrals_by_bank(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT bank_key, COUNT(id) AS cnt
        FROM referrals
        GROUP BY bank_key
        ORDER BY cnt DESC
        """
    ).fetchall()
