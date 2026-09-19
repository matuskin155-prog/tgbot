from datetime import timedelta
from zoneinfo import ZoneInfo

from .google_calendar import CalendarEvent


def format_time_range(event: CalendarEvent, tz: ZoneInfo) -> str:
    """Диапазон начала–конца события в заданном часовом поясе."""
    if event.all_day:
        return _format_all_day_range(event)
    return _format_timed_range(event, tz)


def _format_all_day_range(event: CalendarEvent) -> str:
    start_str = event.start.strftime("%d.%m.%Y")
    if event.end is None:
        return start_str

    # Google хранит конец многодневного all-day события не включительно
    # (это день ПОСЛЕ последнего дня события), поэтому для показа отнимаем сутки.
    inclusive_end = event.end - timedelta(days=1)
    if inclusive_end.date() <= event.start.date():
        return start_str
    return f"{start_str} – {inclusive_end.strftime('%d.%m.%Y')}"


def _format_timed_range(event: CalendarEvent, tz: ZoneInfo) -> str:
    start_local = event.start.astimezone(tz)
    start_str = start_local.strftime("%d.%m.%Y %H:%M")
    if event.end is None:
        return start_str

    end_local = event.end.astimezone(tz)
    if end_local.date() == start_local.date():
        return f"{start_str}–{end_local.strftime('%H:%M')}"
    return f"{start_str} – {end_local.strftime('%d.%m.%Y %H:%M')}"
