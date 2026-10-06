import sqlite3
from contextlib import closing
from typing import List, Optional, Tuple


class Database:
    """SQLite-хранилище подписчиков и уже отправленных напоминаний."""

    def __init__(self, path: str):
        self._path = path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        # timeout и WAL — чтобы бот и веб-приложение (два отдельных процесса)
        # могли безопасно читать/писать в один файл базы одновременно.
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS olympiad_watch (
                    key TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    last_checked_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_changed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS olympiad_events (
                    event_id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
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

    def get_setting(self, key: str) -> Optional[str]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def set_setting_if_absent(self, key: str, value: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )

    def get_olympiad_state(self, key: str) -> Optional[Tuple[str, Optional[str]]]:
        """Возвращает (content_hash, last_changed_at) или None, если ещё не проверялось."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT content_hash, last_changed_at FROM olympiad_watch WHERE key = ?",
                (key,),
            ).fetchone()
            return (row[0], row[1]) if row else None

    def save_olympiad_check(self, key: str, content_hash: str, changed: bool) -> None:
        with closing(self._connect()) as conn, conn:
            if changed:
                conn.execute(
                    """
                    INSERT INTO olympiad_watch (key, content_hash, last_checked_at, last_changed_at)
                    VALUES (?, ?, datetime('now'), datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET
                        content_hash = excluded.content_hash,
                        last_checked_at = excluded.last_checked_at,
                        last_changed_at = excluded.last_changed_at
                    """,
                    (key, content_hash),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO olympiad_watch (key, content_hash, last_checked_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET
                        content_hash = excluded.content_hash,
                        last_checked_at = excluded.last_checked_at
                    """,
                    (key, content_hash),
                )

    def get_olympiad_event_dates(self, event_id: str) -> Optional[Tuple[str, str]]:
        """Возвращает (start_date, end_date) в ISO, если это событие уже
        заводили раньше, иначе None (значит, оно новое)."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT start_date, end_date FROM olympiad_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return (row[0], row[1]) if row else None

    def save_olympiad_event(
        self, event_id: str, source_key: str, start_date: str, end_date: str
    ) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO olympiad_events (event_id, source_key, start_date, end_date, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(event_id) DO UPDATE SET
                    start_date = excluded.start_date,
                    end_date = excluded.end_date,
                    updated_at = excluded.updated_at
                """,
                (event_id, source_key, start_date, end_date),
            )

    def has_upcoming_olympiad_event(self, source_key: str, today_iso: str) -> bool:
        """Есть ли у этого источника хотя бы одно уже заведённое в календарь
        событие, которое ещё не закончилось - если да, страницу пересматривать
        рано, мы уже знаем актуальную дату."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM olympiad_events WHERE source_key = ? AND end_date > ? LIMIT 1",
                (source_key, today_iso),
            ).fetchone()
            return row is not None
