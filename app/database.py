from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import ensure_directories, settings


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    username TEXT NOT NULL COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(room_id, username)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK(kind IN ('text', 'image', 'system')),
    content TEXT NOT NULL DEFAULT '',
    image_name TEXT,
    image_width INTEGER,
    image_height INTEGER,
    reply_to_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_room_id_id ON messages(room_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_users_room ON users(room_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path or settings.database_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    ensure_directories()
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def get_room_by_slug(slug: str) -> dict[str, Any] | None:
    with connect() as conn:
        return row_dict(conn.execute("SELECT * FROM rooms WHERE slug = ?", (slug,)).fetchone())


def get_user(user_id: int, room_id: int | None = None) -> dict[str, Any] | None:
    query = """
        SELECT u.*, r.slug AS room_slug, r.name AS room_name
        FROM users u JOIN rooms r ON r.id = u.room_id
        WHERE u.id = ? AND u.is_active = 1
    """
    params: list[Any] = [user_id]
    if room_id is not None:
        query += " AND u.room_id = ?"
        params.append(room_id)
    with connect() as conn:
        return row_dict(conn.execute(query, params).fetchone())


def authenticate(room_slug: str, username: str) -> dict[str, Any] | None:
    with connect() as conn:
        return row_dict(
            conn.execute(
                """SELECT u.*, r.slug AS room_slug, r.name AS room_name
                   FROM users u JOIN rooms r ON r.id = u.room_id
                   WHERE r.slug = ? AND u.username = ? AND u.is_active = 1""",
                (room_slug.strip(), username.strip()),
            ).fetchone()
        )


def serialize_message(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["deleted"] = bool(item.pop("deleted_at"))
    if item["deleted"]:
        item["content"] = ""
        item["image_name"] = None
    return item


MESSAGE_SELECT = """
SELECT m.id, m.room_id, m.user_id, m.kind, m.content, m.image_name,
       m.image_width, m.image_height, m.reply_to_id, m.created_at, m.deleted_at,
       u.display_name, u.username,
       rm.content AS reply_content, rm.kind AS reply_kind,
       ru.display_name AS reply_display_name
FROM messages m
JOIN users u ON u.id = m.user_id
LEFT JOIN messages rm ON rm.id = m.reply_to_id
LEFT JOIN users ru ON ru.id = rm.user_id
"""


def list_messages(room_id: int, before_id: int | None, limit: int) -> list[dict[str, Any]]:
    query = MESSAGE_SELECT + " WHERE m.room_id = ?"
    params: list[Any] = [room_id]
    if before_id:
        query += " AND m.id < ?"
        params.append(before_id)
    query += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [serialize_message(row) for row in reversed(rows)]


def create_message(
    room_id: int,
    user_id: int,
    kind: str,
    content: str = "",
    image_name: str | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    reply_to_id: int | None = None,
) -> dict[str, Any]:
    if reply_to_id:
        with connect() as conn:
            reply = conn.execute(
                "SELECT id FROM messages WHERE id = ? AND room_id = ? AND deleted_at IS NULL",
                (reply_to_id, room_id),
            ).fetchone()
            if not reply:
                reply_to_id = None
    with connect() as conn:
        cursor = conn.execute(
            """INSERT INTO messages
               (room_id, user_id, kind, content, image_name, image_width, image_height, reply_to_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (room_id, user_id, kind, content, image_name, image_width, image_height, reply_to_id, utc_now()),
        )
        message_id = cursor.lastrowid
        row = conn.execute(MESSAGE_SELECT + " WHERE m.id = ?", (message_id,)).fetchone()
    assert row is not None
    return serialize_message(row)


def mark_message_deleted(message_id: int, room_id: int, user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT image_name FROM messages WHERE id = ? AND room_id = ? AND user_id = ? AND deleted_at IS NULL",
            (message_id, room_id, user_id),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE messages SET deleted_at = ?, content = '', image_name = NULL WHERE id = ?",
            (utc_now(), message_id),
        )
        return dict(row)


def image_belongs_to_room(image_name: str, room_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM messages WHERE image_name = ? AND room_id = ? AND deleted_at IS NULL",
            (image_name, room_id),
        ).fetchone()
    return row is not None

