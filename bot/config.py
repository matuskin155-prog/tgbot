import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _parse_minutes(raw: str) -> List[int]:
    minutes = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            minutes.append(int(part))
    if not minutes:
        raise ValueError("REMINDER_MINUTES_BEFORE не может быть пустым")
    return sorted(set(minutes), reverse=True)


def _parse_admin_ids(raw: str) -> List[int]:
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    return ids


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    google_calendar_id: str
    google_service_account_file: str
    reminder_minutes_before: List[int]
    poll_interval_seconds: int
    lookahead_hours: int
    timezone: str
    database_path: str
    admin_chat_ids: List[int]


def load_settings() -> Settings:
    telegram_token = os.environ["TELEGRAM_BOT_TOKEN"]

    return Settings(
        telegram_token=telegram_token,
        google_calendar_id=os.environ.get("GOOGLE_CALENDAR_ID", "primary"),
        google_service_account_file=os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"
        ),
        reminder_minutes_before=_parse_minutes(
            os.environ.get("REMINDER_MINUTES_BEFORE", "60,10")
        ),
        poll_interval_seconds=int(os.environ.get("POLL_INTERVAL_SECONDS", "60")),
        lookahead_hours=int(os.environ.get("LOOKAHEAD_HOURS", "24")),
        timezone=os.environ.get("TIMEZONE", "UTC"),
        database_path=os.environ.get("DATABASE_PATH", "bot_data.sqlite3"),
        admin_chat_ids=_parse_admin_ids(os.environ.get("ADMIN_CHAT_IDS", "")),
    )
