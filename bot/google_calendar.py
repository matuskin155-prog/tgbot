from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


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


class GoogleCalendarClient:
    """Тонкая обёртка над Google Calendar API для сервис-аккаунта."""

    def __init__(self, service_account_file: str, calendar_id: str):
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=SCOPES
        )
        self._service = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        )
        self._calendar_id = calendar_id

    def get_upcoming_events(self, lookahead_hours: int) -> List[CalendarEvent]:
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(hours=lookahead_hours)

        events_result = (
            self._service.events()
            .list(
                calendarId=self._calendar_id,
                timeMin=now.isoformat(),
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
        )
