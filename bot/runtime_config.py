from dataclasses import dataclass
from datetime import datetime, time
from typing import List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .database import Database


class ConfigError(ValueError):
    """Некорректное значение настройки, введённое пользователем в Telegram."""


@dataclass
class Defaults:
    calendar_id: str
    reminder_minutes_before: List[int]
    poll_interval_seconds: int
    lookahead_hours: int
    timezone: str
    daily_digest_time: str


class RuntimeConfig:
    """Настройки бота, которые можно менять из Telegram без перезапуска.

    Хранятся в SQLite (таблица settings) и на первом запуске заполняются
    значениями по умолчанию из .env. После этого .env для этих параметров
    больше не читается — источником истины становится база данных.
    """

    def __init__(self, db: Database, defaults: Defaults):
        self._db = db
        self._seed_defaults(defaults)

    def _seed_defaults(self, defaults: Defaults) -> None:
        self._db.set_setting_if_absent("calendar_id", defaults.calendar_id)
        self._db.set_setting_if_absent(
            "reminder_minutes_before", _format_minutes(defaults.reminder_minutes_before)
        )
        self._db.set_setting_if_absent(
            "poll_interval_seconds", str(defaults.poll_interval_seconds)
        )
        self._db.set_setting_if_absent("lookahead_hours", str(defaults.lookahead_hours))
        self._db.set_setting_if_absent("timezone", defaults.timezone)
        self._db.set_setting_if_absent("daily_digest_time", defaults.daily_digest_time)

    @property
    def calendar_id(self) -> str:
        return self._db.get_setting("calendar_id")

    def set_calendar_id(self, value: str) -> None:
        value = value.strip()
        if not value:
            raise ConfigError("ID календаря не может быть пустым")
        self._db.set_setting("calendar_id", value)

    @property
    def reminder_minutes_before(self) -> List[int]:
        return _parse_minutes(self._db.get_setting("reminder_minutes_before"))

    def set_reminder_minutes_before(self, raw: str) -> None:
        minutes = _parse_minutes(raw)
        self._db.set_setting("reminder_minutes_before", _format_minutes(minutes))

    @property
    def poll_interval_seconds(self) -> int:
        return int(self._db.get_setting("poll_interval_seconds"))

    def set_poll_interval_seconds(self, raw: str) -> int:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ConfigError("Интервал опроса должен быть целым числом секунд") from exc
        if value < 15:
            raise ConfigError("Интервал опроса не может быть меньше 15 секунд")
        self._db.set_setting("poll_interval_seconds", str(value))
        return value

    @property
    def lookahead_hours(self) -> int:
        return int(self._db.get_setting("lookahead_hours"))

    def set_lookahead_hours(self, raw: str) -> None:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ConfigError("Горизонт просмотра должен быть целым числом часов") from exc
        if value < 1:
            raise ConfigError("Горизонт просмотра должен быть не меньше 1 часа")
        self._db.set_setting("lookahead_hours", str(value))

    @property
    def timezone(self) -> str:
        return self._db.get_setting("timezone")

    def set_timezone(self, value: str) -> None:
        value = value.strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(
                f"Неизвестный часовой пояс «{value}». Пример: Europe/Moscow"
            ) from exc
        self._db.set_setting("timezone", value)

    @property
    def daily_digest_time(self) -> str:
        return self._db.get_setting("daily_digest_time")

    @property
    def daily_digest_time_obj(self) -> time:
        return _parse_digest_time(self.daily_digest_time)

    def set_daily_digest_time(self, raw: str) -> time:
        parsed = _parse_digest_time(raw)
        self._db.set_setting("daily_digest_time", parsed.strftime("%H:%M"))
        return parsed

    def as_dict(self) -> dict:
        return {
            "calendar_id": self.calendar_id,
            "reminder_minutes_before": ", ".join(str(m) for m in self.reminder_minutes_before),
            "poll_interval_seconds": self.poll_interval_seconds,
            "lookahead_hours": self.lookahead_hours,
            "timezone": self.timezone,
            "daily_digest_time": self.daily_digest_time,
        }


def _parse_minutes(raw: str) -> List[int]:
    minutes = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            minutes.append(int(part))
        except ValueError as exc:
            raise ConfigError(
                "Список должен быть числами через запятую, например: 60,10"
            ) from exc
    if not minutes:
        raise ConfigError("Нужно указать хотя бы одно значение, например: 60,10")
    return sorted(set(minutes), reverse=True)


def _format_minutes(minutes: List[int]) -> str:
    return ",".join(str(m) for m in minutes)


def _parse_digest_time(raw: str) -> time:
    try:
        return datetime.strptime(raw.strip(), "%H:%M").time()
    except ValueError as exc:
        raise ConfigError("Время должно быть в формате ЧЧ:ММ, например: 10:00") from exc
