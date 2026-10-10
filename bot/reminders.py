import asyncio
import logging
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .database import Database
from .formatting import event_end_date, format_time_range
from .google_calendar import CalendarEvent, GoogleCalendarClient
from .olympiads import olympiad_url_for
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

    # Подписчик мог лично скрыть у себя какое-то событие (не трогая сам
    # календарь) - такому chat_id напоминания по нему больше не шлём.
    hidden_by_chat = {chat_id: db.get_hidden_event_ids_for_chat(chat_id) for chat_id in subscribers}

    try:
        events = await asyncio.to_thread(
            calendar.get_upcoming_events, runtime.lookahead_hours, runtime.calendar_id
        )
    except Exception:
        logger.exception("Не удалось получить события из Google Calendar")
        return

    now = datetime.now(timezone.utc)
    tz = ZoneInfo(runtime.timezone)
    today_local = now.astimezone(tz).date()

    for event in events:
        minutes_until = (event.start - now).total_seconds() / 60
        if minutes_until > 0:
            for minutes_before in runtime.reminder_minutes_before:
                if minutes_until > minutes_before:
                    continue

                for chat_id in subscribers:
                    if event.id in hidden_by_chat[chat_id]:
                        continue
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

        # Отдельно - напоминания о приближающемся закрытии олимпиадного окна
        # (регистрация/отборочный этап). Обычные напоминания выше считают от
        # НАЧАЛА события в минутах - для многодневного all-day окна это почти
        # бесполезно (сработает один раз в момент открытия, а не когда
        # дедлайн уже близко). Здесь же считаем от КОНЦА события в днях.
        if event.all_day:
            url = olympiad_url_for(event)
            if url:
                end_date = event_end_date(event, tz)
                if end_date is not None:
                    days_left = (end_date - today_local).days
                    if days_left >= 0:
                        for days_before in runtime.olympiad_deadline_days_before:
                            if days_left > days_before:
                                continue

                            # Отрицательный ключ - чтобы не столкнуться с
                            # положительными minutes_before обычных
                            # напоминаний в той же таблице sent_reminders.
                            deadline_key = -days_before - 1
                            for chat_id in subscribers:
                                if event.id in hidden_by_chat[chat_id]:
                                    continue
                                if db.has_sent_reminder(event.id, deadline_key, chat_id):
                                    continue

                                text = _format_deadline_reminder(event, days_before, tz, url)
                                try:
                                    await context.bot.send_message(
                                        chat_id=chat_id,
                                        text=text,
                                        parse_mode=ParseMode.HTML,
                                        disable_web_page_preview=True,
                                    )
                                except TelegramError:
                                    logger.exception(
                                        "Не удалось отправить напоминание о дедлайне в чат %s", chat_id
                                    )
                                    continue

                                db.mark_reminder_sent(event.id, deadline_key, chat_id)

    db.prune_old_reminders()


def _format_reminder(event: CalendarEvent, minutes_before: int, tz: ZoneInfo) -> str:
    when_label = _format_minutes(minutes_before)
    event_time = format_time_range(event, tz)

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


def _format_deadline_reminder(event: CalendarEvent, days_before: int, tz: ZoneInfo, url: str) -> str:
    when_label = _format_days_left(days_before)
    event_time = format_time_range(event, tz)

    lines = [
        f"⏳ <b>Дедлайн олимпиады</b> — {when_label}",
        f"<b>{escape(event.summary)}</b>",
        f"🕒 {event_time}",
        f'<a href="{escape(url)}">Сайт олимпиады</a>',
    ]
    if event.html_link:
        lines.append(f'<a href="{event.html_link}">Открыть в Google Calendar</a>')
    return "\n".join(lines)


def _format_days_left(days: int) -> str:
    if days == 0:
        return "сегодня последний день!"
    if days == 1:
        return "завтра последний день"
    mod10 = days % 10
    mod100 = days % 100
    if 11 <= mod100 <= 14:
        word = "дней"
    elif mod10 == 1:
        word = "день"
    elif 2 <= mod10 <= 4:
        word = "дня"
    else:
        word = "дней"
    return f"осталось {days} {word}"
