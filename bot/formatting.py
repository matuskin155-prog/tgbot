from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from .google_calendar import CalendarEvent


def format_time_range(event: CalendarEvent, tz: ZoneInfo) -> str:
    """Диапазон начала–конца события в заданном часовом поясе.

    Если событие уже идёт прямо сейчас, начало (которое уже прошло) не
    показываем — только то, когда оно закончится."""
    if event.all_day:
        return _format_all_day_range(event)
    return _format_timed_range(event, tz)


def format_event_line(event: CalendarEvent, tz: ZoneInfo) -> str:
    """Одна строка списка событий: диапазон времени, название, место."""
    when = format_time_range(event, tz)
    line = f"• {when} — {escape(event.summary)}"
    if event.location:
        line += f" ({escape(event.location)})"
    return line


def _format_all_day_range(event: CalendarEvent) -> str:
    start_str = event.start.strftime("%d.%m.%Y")
    if event.end is None:
        return start_str

    # Google хранит конец многодневного all-day события не включительно
    # (это день ПОСЛЕ последнего дня события), поэтому для показа отнимаем сутки.
    inclusive_end = event.end - timedelta(days=1)
    if inclusive_end.date() <= event.start.date():
        return start_str

    today = datetime.now(timezone.utc).date()
    if event.start.date() < today <= inclusive_end.date():
        return f"идёт сейчас, до {inclusive_end.strftime('%d.%m.%Y')}"
    return f"{start_str} – {inclusive_end.strftime('%d.%m.%Y')}"


def _format_timed_range(event: CalendarEvent, tz: ZoneInfo) -> str:
    start_local = event.start.astimezone(tz)
    start_str = start_local.strftime("%d.%m.%Y %H:%M")
    if event.end is None:
        return start_str

    end_local = event.end.astimezone(tz)
    now = datetime.now(timezone.utc)
    if event.start <= now <= event.end:
        if end_local.date() == now.astimezone(tz).date():
            return f"идёт сейчас, до {end_local.strftime('%H:%M')}"
        return f"идёт сейчас, до {end_local.strftime('%d.%m.%Y %H:%M')}"

    if end_local.date() == start_local.date():
        return f"{start_str}–{end_local.strftime('%H:%M')}"
    return f"{start_str} – {end_local.strftime('%d.%m.%Y %H:%M')}"
