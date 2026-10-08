from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Optional
from zoneinfo import ZoneInfo

from .google_calendar import CalendarEvent


def event_end_date(event: CalendarEvent, tz: ZoneInfo) -> Optional[date]:
    """Последний день, когда событие ещё актуально, в часовом поясе tz -
    например, для определения, сколько дней осталось до закрытия
    многодневного окна регистрации/отборочного этапа олимпиады.

    Google хранит дату конца all-day события исключительной (день ПОСЛЕ
    последнего дня события) - сдвигаем на день назад. У all-day событий сам
    end размечен условным UTC без реального смысла часового пояса (это
    просто то, как _parse_event в google_calendar.py кодирует голую дату),
    поэтому пересчитывать его в tz нужно именно так, а не интерпретировать
    время "как есть"."""
    if event.end is None:
        return None
    end_date = event.end.astimezone(tz).date()
    if event.all_day:
        end_date -= timedelta(days=1)
    return end_date


def is_event_ongoing(event: CalendarEvent) -> bool:
    """Идёт ли событие прямо сейчас (между его началом и концом)."""
    if event.end is None:
        return False
    if event.all_day:
        today = datetime.now(timezone.utc).date()
        inclusive_end = (event.end - timedelta(days=1)).date()
        return event.start.date() < today <= inclusive_end
    now = datetime.now(timezone.utc)
    return event.start <= now <= event.end


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

    if is_event_ongoing(event):
        return f"идёт сейчас, до {inclusive_end.strftime('%d.%m.%Y')}"
    return f"{start_str} – {inclusive_end.strftime('%d.%m.%Y')}"


def _format_timed_range(event: CalendarEvent, tz: ZoneInfo) -> str:
    start_local = event.start.astimezone(tz)
    start_str = start_local.strftime("%d.%m.%Y %H:%M")
    if event.end is None:
        return start_str

    end_local = event.end.astimezone(tz)
    if is_event_ongoing(event):
        now_local = datetime.now(timezone.utc).astimezone(tz)
        if end_local.date() == now_local.date():
            return f"идёт сейчас, до {end_local.strftime('%H:%M')}"
        return f"идёт сейчас, до {end_local.strftime('%d.%m.%Y %H:%M')}"

    if end_local.date() == start_local.date():
        return f"{start_str}–{end_local.strftime('%H:%M')}"
    return f"{start_str} – {end_local.strftime('%d.%m.%Y %H:%M')}"
