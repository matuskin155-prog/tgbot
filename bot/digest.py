import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .database import Database
from .formatting import format_event_line
from .google_calendar import CalendarEvent, GoogleCalendarClient
from .runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)


async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ежедневная сводка событий на сегодня — уходит всем подписчикам."""
    db: Database = context.bot_data["db"]
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]

    subscribers = db.list_subscribers()
    if not subscribers:
        return

    tz = ZoneInfo(runtime.timezone)
    today = datetime.now(tz).date()

    try:
        events = await asyncio.to_thread(
            calendar.get_events_for_day, today, runtime.calendar_id, tz
        )
    except Exception:
        logger.exception("Не удалось получить события для ежедневной сводки")
        return

    text = _format_digest(events, tz)

    for chat_id in subscribers:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramError:
            logger.exception("Не удалось отправить сводку в чат %s", chat_id)


def _format_digest(events: list[CalendarEvent], tz: ZoneInfo) -> str:
    if not events:
        return "<b>Доброе утро! На сегодня событий нет</b> 🎉"

    lines = ["<b>Доброе утро! События на сегодня:</b>"]
    lines.extend(format_event_line(event, tz) for event in events)
    return "\n".join(lines)
