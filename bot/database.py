import sqlite3
from contextlib import closing
from typing import List


class Database:
    """SQLite-хранилище подписчиков и уже отправленных напоминаний."""

    def __init__(self, path: str):
        self._path = path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_reminders (
                    event_id TEXT NOT NULL,
                    minutes_before INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (event_id, minutes_before, chat_id)
                )
                """
            )

    def add_subscriber(self, chat_id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,)
            )
            return cur.rowcount > 0

    def remove_subscriber(self, chat_id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
            return cur.rowcount > 0

    def list_subscribers(self) -> List[int]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT chat_id FROM subscribers").fetchall()
            return [row[0] for row in rows]

    def is_subscribed(self, chat_id: int) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM subscribers WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            return row is not None

    def has_sent_reminder(self, event_id: str, minutes_before: int, chat_id: int) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM sent_reminders
                WHERE event_id = ? AND minutes_before = ? AND chat_id = ?
                """,
                (event_id, minutes_before, chat_id),
            ).fetchone()
            return row is not None

    def mark_reminder_sent(self, event_id: str, minutes_before: int, chat_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sent_reminders (event_id, minutes_before, chat_id)
                VALUES (?, ?, ?)
                """,
                (event_id, minutes_before, chat_id),
            )

    def prune_old_reminders(self, older_than_days: int = 7) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "DELETE FROM sent_reminders WHERE sent_at < datetime('now', ?)",
                (f"-{older_than_days} days",),
            )
