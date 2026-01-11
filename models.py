import os
import psycopg2
from psycopg2.extras import RealDictCursor
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
    id SERIAL PRIMARY KEY,
    tg_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS referrals (
    id SERIAL PRIMARY KEY,
    referrer_id INTEGER NOT NULL,
    referred_id INTEGER UNIQUE NOT NULL,
    bank_key TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
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

CREATE TABLE IF NOT EXISTS reward_requests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    bank_key TEXT NOT NULL,
    phone TEXT NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
"""


def get_connection() -> psycopg2.extensions.connection:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("❗ DATABASE_URL is not set in environment")
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    conn.autocommit = True
    return conn


def init_db(banks: Iterable[Bank]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.executemany(
                "INSERT INTO banks (key, base_url) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                [(bank.key, bank.base_url) for bank in banks],
            )


def ensure_user(
    conn: psycopg2.extensions.connection,
    tg_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
) -> int:
    now = datetime.utcnow().isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (tg_id, username, first_name, last_name, created_at)"
            " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (tg_id) DO NOTHING",
            (tg_id, username, first_name, last_name, now),
        )
        cur.execute("SELECT id FROM users WHERE tg_id = %s", (tg_id,))
        row = cur.fetchone()
        return int(row["id"])


def get_user_id(conn: psycopg2.extensions.connection, tg_id: int) -> Optional[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE tg_id = %s", (tg_id,))
        row = cur.fetchone()
    if not row:
        return None
    return int(row["id"])


def has_referral(conn: psycopg2.extensions.connection, referred_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM referrals WHERE referred_id = %s", (referred_id,))
        row = cur.fetchone()
    return row is not None


def create_referral(
    conn: psycopg2.extensions.connection,
    referrer_id: int,
    referred_id: int,
    bank_key: str,
) -> None:
    now = datetime.utcnow().isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO referrals (referrer_id, referred_id, bank_key, created_at)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT (referred_id) DO NOTHING",
            (referrer_id, referred_id, bank_key, now),
        )


def list_banks(conn: psycopg2.extensions.connection) -> list[Bank]:
    with conn.cursor() as cur:
        cur.execute("SELECT key, base_url FROM banks ORDER BY key")
        rows = cur.fetchall()
    return [Bank(key=row["key"], base_url=row["base_url"]) for row in rows]


def add_bank(conn: psycopg2.extensions.connection, key: str, base_url: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM banks WHERE key = %s", (key,))
        if cur.fetchone():
            return False
        cur.execute("INSERT INTO banks (key, base_url) VALUES (%s, %s)", (key, base_url))
        return True


def update_bank_url(conn: psycopg2.extensions.connection, key: str, base_url: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE banks SET base_url = %s WHERE key = %s",
            (base_url, key),
        )


def delete_bank(conn: psycopg2.extensions.connection, key: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM banks WHERE key = %s", (key,))


def get_setting(conn: psycopg2.extensions.connection, key: str) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
        row = cur.fetchone()
    if not row:
        return None
    return str(row["value"])


def set_setting(conn: psycopg2.extensions.connection, key: str, value: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s)"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value),
        )


def has_pending_reward_request(conn: psycopg2.extensions.connection, user_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM reward_requests WHERE user_id = %s AND status = %s",
            (user_id, "pending"),
        )
        row = cur.fetchone()
    return row is not None


def create_reward_request(
    conn: psycopg2.extensions.connection,
    user_id: int,
    bank_key: str,
    phone: str,
    first_name: str,
    last_name: str,
) -> None:
    now = datetime.utcnow().isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO reward_requests (user_id, bank_key, phone, first_name, last_name, status, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, bank_key, phone, first_name, last_name, "pending", now),
        )


def list_reward_requests(conn: psycopg2.extensions.connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rr.id,
                   rr.user_id,
                   rr.bank_key,
                   rr.phone,
                   rr.first_name,
                   rr.last_name,
                   rr.status,
                   rr.created_at,
                   u.tg_id,
                   u.username,
                   u.first_name AS tg_first_name,
                   u.last_name AS tg_last_name
            FROM reward_requests rr
            JOIN users u ON u.id = rr.user_id
            WHERE rr.status = 'pending'
            ORDER BY rr.created_at DESC
            """
        )
        return cur.fetchall()


def list_reward_history(conn: psycopg2.extensions.connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rr.id,
                   rr.user_id,
                   rr.bank_key,
                   rr.phone,
                   rr.first_name,
                   rr.last_name,
                   rr.status,
                   rr.created_at,
                   u.tg_id,
                   u.username,
                   u.first_name AS tg_first_name,
                   u.last_name AS tg_last_name
            FROM reward_requests rr
            JOIN users u ON u.id = rr.user_id
            WHERE rr.status IN ('approved', 'rejected')
            ORDER BY rr.created_at DESC
            """
        )
        return cur.fetchall()


def get_reward_request(conn: psycopg2.extensions.connection, request_id: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rr.id,
                   rr.user_id,
                   rr.bank_key,
                   rr.phone,
                   rr.first_name,
                   rr.last_name,
                   rr.status,
                   rr.created_at,
                   u.tg_id,
                   u.username,
                   u.first_name AS tg_first_name,
                   u.last_name AS tg_last_name
            FROM reward_requests rr
            JOIN users u ON u.id = rr.user_id
            WHERE rr.id = %s
            """,
            (request_id,),
        )
        return cur.fetchone()


def update_reward_request_status(
    conn: psycopg2.extensions.connection, request_id: int, status: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE reward_requests SET status = %s WHERE id = %s",
            (status, request_id),
        )


def count_users(conn: psycopg2.extensions.connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM users")
        row = cur.fetchone()
    return int(row["cnt"])


def count_reward_requests_by_status(conn: psycopg2.extensions.connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM reward_requests
            GROUP BY status
            """
        )
        rows = cur.fetchall()
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    for row in rows:
        counts[row["status"]] = int(row["cnt"])
    return counts


def top_referrers(conn: psycopg2.extensions.connection, limit: int = 10) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.tg_id, u.username, u.first_name, u.last_name, COUNT(r.id) AS cnt
            FROM users u
            JOIN referrals r ON r.referrer_id = u.id
            GROUP BY u.id
            ORDER BY cnt DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def referrals_by_bank(conn: psycopg2.extensions.connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bank_key, COUNT(id) AS cnt
            FROM referrals
            GROUP BY bank_key
            ORDER BY cnt DESC
            """
        )
        return cur.fetchall()
