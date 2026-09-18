import asyncio
import logging
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .config import Settings
from .database import Database
from .google_calendar import CalendarEvent, GoogleCalendarClient

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Привет! Я присылаю напоминания о событиях из Google Calendar.\n\n"
    "Команды:\n"
    "/subscribe — включить напоминания в этом чате\n"
    "/unsubscribe — выключить напоминания\n"
    "/today — события на ближайшие 24 часа\n"
    "/upcoming — все события в пределах горизонта просмотра\n"
    "/status — текущие настройки"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME_TEXT)


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    chat_id = update.effective_chat.id
    if db.add_subscriber(chat_id):
        await update.effective_message.reply_text(
            "Готово! Буду присылать сюда напоминания о событиях."
        )
    else:
        await update.effective_message.reply_text("Этот чат уже подписан на напоминания.")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    chat_id = update.effective_chat.id
    if db.remove_subscriber(chat_id):
        await update.effective_message.reply_text("Напоминания для этого чата отключены.")
    else:
        await update.effective_message.reply_text("Этот чат и так не был подписан.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    db: Database = context.bot_data["db"]
    chat_id = update.effective_chat.id
    subscribed = db.is_subscribed(chat_id)
    minutes = ", ".join(str(m) for m in settings.reminder_minutes_before)
    text = (
        f"Подписка: {'включена' if subscribed else 'выключена'}\n"
        f"Календарь: {settings.google_calendar_id}\n"
        f"Напоминания за (мин): {minutes}\n"
        f"Горизонт просмотра: {settings.lookahead_hours} ч.\n"
        f"Опрос календаря: каждые {settings.poll_interval_seconds} сек."
    )
    await update.effective_message.reply_text(text)


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_events(update, context, hours=24, title="Ближайшие 24 часа")


async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    await _send_events(
        update, context, hours=settings.lookahead_hours, title="Ближайшие события"
    )


async def _send_events(update: Update, context: ContextTypes.DEFAULT_TYPE, hours: int, title: str) -> None:
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    settings: Settings = context.bot_data["settings"]

    try:
        events = await asyncio.to_thread(calendar.get_upcoming_events, hours)
    except Exception:
        logger.exception("Не удалось получить события для команды %s", title)
        await update.effective_message.reply_text("Не получилось получить события из календаря 😕")
        return

    if not events:
        await update.effective_message.reply_text(f"{title}: событий нет.")
        return

    tz = ZoneInfo(settings.timezone)
    lines = [f"<b>{title}</b>"]
    lines.extend(_format_event_line(event, tz) for event in events)

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


def _format_event_line(event: CalendarEvent, tz: ZoneInfo) -> str:
    if event.all_day:
        when = event.start.strftime("%d.%m")
    else:
        when = event.start.astimezone(tz).strftime("%d.%m %H:%M")

    line = f"• {when} — {event.summary}"
    if event.location:
        line += f" ({event.location})"
    return line
