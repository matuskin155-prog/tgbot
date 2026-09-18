import asyncio
import logging
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .database import Database
from .google_calendar import CalendarEvent, GoogleCalendarClient
from .runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)


async def check_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Периодическая задача: тянет события из календаря и рассылает напоминания."""
    db: Database = context.bot_data["db"]
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]

    subscribers = db.list_subscribers()
    if not subscribers:
        return

    try:
        events = await asyncio.to_thread(
            calendar.get_upcoming_events, runtime.lookahead_hours, runtime.calendar_id
        )
    except Exception:
        logger.exception("Не удалось получить события из Google Calendar")
        return

    now = datetime.now(timezone.utc)
    tz = ZoneInfo(runtime.timezone)

    for event in events:
        minutes_until = (event.start - now).total_seconds() / 60
        if minutes_until <= 0:
            continue

        for minutes_before in runtime.reminder_minutes_before:
            if minutes_until > minutes_before:
                continue

            for chat_id in subscribers:
                if db.has_sent_reminder(event.id, minutes_before, chat_id):
                    continue

                text = _format_reminder(event, minutes_before, tz)
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except TelegramError:
                    logger.exception("Не удалось отправить напоминание в чат %s", chat_id)
                    continue

                db.mark_reminder_sent(event.id, minutes_before, chat_id)

    db.prune_old_reminders()


def _format_reminder(event: CalendarEvent, minutes_before: int, tz: ZoneInfo) -> str:
    when_label = _format_minutes(minutes_before)
    if event.all_day:
        event_time = event.start.strftime("%d.%m")
    else:
        event_time = event.start.astimezone(tz).strftime("%d.%m в %H:%M")

    lines = [
        f"⏰ <b>Напоминание</b> — {when_label}",
        f"<b>{escape(event.summary)}</b>",
        f"🕒 {event_time}",
    ]
    if event.location:
        lines.append(f"📍 {escape(event.location)}")
    if event.description:
        lines.append(escape(event.description[:300]))
    if event.html_link:
        lines.append(f'<a href="{event.html_link}">Открыть в Google Calendar</a>')
    return "\n".join(lines)


def _format_minutes(minutes: int) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        return "через 1 ч." if hours == 1 else f"через {hours} ч."
    return f"через {minutes} мин."
