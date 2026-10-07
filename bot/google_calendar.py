import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: Optional[datetime]
    location: Optional[str]
    description: Optional[str]
    html_link: Optional[str]
    all_day: bool
    # Собственные метаданные бота (extendedProperties.private в Google
    # Calendar) - например, olympiad_url у событий, автозаведённых по
    # олимпиадам (см. bot/olympiad_watch.py). Обычных событий не касается.
    extended_properties: Dict[str, str] = field(default_factory=dict)


class GoogleCalendarClient:
    """Тонкая обёртка над Google Calendar API для сервис-аккаунта."""

    def __init__(self, service_account_file: str):
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=SCOPES
        )
        self._service = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        )
        # Один и тот же self._service (а под ним — httplib2-транспорт, он не
        # thread-safe) вызывается из разных потоков через asyncio.to_thread
        # и командами в чате, и фоновыми задачами одновременно. Лок сериализует
        # обращения, чтобы не ловить редкие гонки при параллельных запросах.
        self._lock = threading.Lock()

    def get_upcoming_events(self, lookahead_hours: int, calendar_id: str) -> List[CalendarEvent]:
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(hours=lookahead_hours)
        return self._list_events(now, time_max, calendar_id)

    def get_events_for_day(self, day: date, calendar_id: str, tz: ZoneInfo) -> List[CalendarEvent]:
        """Все события за указанный календарный день в часовом поясе tz."""
        start_of_day = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)
        end_of_day = start_of_day + timedelta(days=1)
        return self._list_events(start_of_day, end_of_day, calendar_id)

    def get_events_in_range(
        self, time_min: datetime, time_max: datetime, calendar_id: str
    ) -> List[CalendarEvent]:
        """Все события в произвольном явном диапазоне - используется
        интерактивным календарём в Mini App для показа любого месяца
        (вперёд/назад от текущего), в отличие от get_upcoming_events
        (всегда строго "от сейчас на N часов вперёд")."""
        return self._list_events(time_min, time_max, calendar_id)

    def get_event(self, event_id: str, calendar_id: str) -> CalendarEvent:
        with self._lock:
            item = self._service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        return self._parse_event(item)

    def delete_event(self, event_id: str, calendar_id: str) -> None:
        with self._lock:
            self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    def upsert_event(
        self,
        event_id: str,
        calendar_id: str,
        summary: str,
        description: str,
        start_date: date,
        end_date: date,
        extended_properties: Optional[Dict[str, str]] = None,
    ) -> None:
        """Создаёт all-day событие с заданным id, либо обновляет его, если
        событие с таким id уже есть (используется для автодобавления
        олимпиад — event_id стабилен между проверками, повторный вызов
        с тем же id не создаёт дубликат, а актуализирует даты/описание).

        extended_properties — произвольные строковые метаданные бота
        (например, ссылка на сайт-первоисточник), не показываются в самом
        Google Calendar, но возвращаются обратно через API."""
        body = {
            "summary": summary,
            "description": description,
            "start": {"date": start_date.isoformat()},
            "end": {"date": end_date.isoformat()},
        }
        if extended_properties:
            body["extendedProperties"] = {"private": extended_properties}
        with self._lock:
            try:
                self._service.events().insert(
                    calendarId=calendar_id, body={**body, "id": event_id}
                ).execute()
            except HttpError as exc:
                if exc.resp.status == 409:
                    self._service.events().update(
                        calendarId=calendar_id, eventId=event_id, body=body
                    ).execute()
                else:
                    raise

    def _list_events(
        self, time_min: datetime, time_max: datetime, calendar_id: str
    ) -> List[CalendarEvent]:
        with self._lock:
            events_result = (
                self._service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

        events = []
        for item in events_result.get("items", []):
            if item.get("status") == "cancelled":
                continue
            events.append(self._parse_event(item))
        return events

    @staticmethod
    def _parse_event(item: dict) -> CalendarEvent:
        start_raw = item["start"]
        end_raw = item.get("end", {})
        all_day = "date" in start_raw

        if all_day:
            start = datetime.fromisoformat(start_raw["date"]).replace(tzinfo=timezone.utc)
            end = (
                datetime.fromisoformat(end_raw["date"]).replace(tzinfo=timezone.utc)
                if end_raw.get("date")
                else None
            )
        else:
            start = datetime.fromisoformat(start_raw["dateTime"])
            end = (
                datetime.fromisoformat(end_raw["dateTime"])
                if end_raw.get("dateTime")
                else None
            )

        return CalendarEvent(
            id=item["id"],
            summary=item.get("summary", "(без названия)"),
            start=start,
            end=end,
            location=item.get("location"),
            description=item.get("description"),
            html_link=item.get("htmlLink"),
            all_day=all_day,
            extended_properties=item.get("extendedProperties", {}).get("private", {}),
        )
