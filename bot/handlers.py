import asyncio
import logging
from html import escape
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .config import Settings
from .database import Database
from .digest import send_daily_digest
from .formatting import format_event_line
from .google_calendar import GoogleCalendarClient
from .reminders import check_reminders
from .runtime_config import ConfigError, RuntimeConfig

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Привет! Я присылаю напоминания о событиях из общего Google Calendar — "
    "подписаться на них может любой, кто напишет мне /subscribe.\n\n"
    "Команды:\n"
    "/subscribe — включить напоминания в этом чате\n"
    "/unsubscribe — выключить напоминания\n"
    "/today — события на ближайшие 24 часа\n"
    "/upcoming — все события в пределах горизонта просмотра\n"
    "/status — текущие настройки\n"
    "/whoami — узнать свой chat_id\n\n"
    "Каждый день в заданное время я также присылаю сводку событий на сегодня "
    "всем, кто подписан (/status покажет, во сколько)."
)

ADMIN_HELP_TEXT = (
    "\n\nКоманды администратора (только для ADMIN_CHAT_IDS):\n"
    "/config — показать текущие настройки\n"
    "/set_calendar <id> — сменить календарь\n"
    "/set_reminders <60,10> — за сколько минут напоминать\n"
    "/set_lookahead <часы> — горизонт просмотра\n"
    "/set_interval <секунды> — как часто опрашивать календарь\n"
    "/set_timezone <Europe/Moscow> — часовой пояс\n"
    "/set_digest_time <ЧЧ:ММ> — время ежедневной сводки"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = WELCOME_TEXT
    if _is_admin(update, context):
        text += ADMIN_HELP_TEXT
    await update.effective_message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"Ваш chat_id: {update.effective_chat.id}")


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
    db: Database = context.bot_data["db"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    chat_id = update.effective_chat.id
    subscribed = db.is_subscribed(chat_id)
    cfg = runtime.as_dict()
    text = (
        f"Подписка: {'включена' if subscribed else 'выключена'}\n"
        f"Календарь: {cfg['calendar_id']}\n"
        f"Напоминания за (мин): {cfg['reminder_minutes_before']}\n"
        f"Горизонт просмотра: {cfg['lookahead_hours']} ч.\n"
        f"Опрос календаря: каждые {cfg['poll_interval_seconds']} сек.\n"
        f"Ежедневная сводка: в {cfg['daily_digest_time']} ({cfg['timezone']})"
    )
    await update.effective_message.reply_text(text)


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_events(update, context, hours=24, title="Ближайшие 24 часа")


async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    await _send_events(update, context, hours=runtime.lookahead_hours, title="Ближайшие события")


async def _send_events(update: Update, context: ContextTypes.DEFAULT_TYPE, hours: int, title: str) -> None:
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]

    try:
        events = await asyncio.to_thread(calendar.get_upcoming_events, hours, runtime.calendar_id)
    except Exception:
        logger.exception("Не удалось получить события для команды %s", title)
        await update.effective_message.reply_text("Не получилось получить события из календаря 😕")
        return

    if not events:
        await update.effective_message.reply_text(f"{title}: событий нет.")
        return

    tz = ZoneInfo(runtime.timezone)
    lines = [f"<b>{title}</b>"]
    lines.extend(format_event_line(event, tz) for event in events)

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


# --- Команды администратора: настройка бота прямо из Telegram ---


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings: Settings = context.bot_data["settings"]
    return update.effective_chat.id in settings.admin_chat_ids


async def _require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings: Settings = context.bot_data["settings"]
    if not settings.admin_chat_ids:
        await update.effective_message.reply_text(
            "Настройка через бота выключена.\n"
            "Узнайте свой chat_id командой /whoami, впишите его в ADMIN_CHAT_IDS "
            "в файле .env и перезапустите бота."
        )
        return False
    if not _is_admin(update, context):
        await update.effective_message.reply_text(
            "Эта команда доступна только администратору бота."
        )
        return False
    return True


async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    cfg = runtime.as_dict()
    text = (
        "<b>Текущие настройки</b>\n"
        f"Календарь: {escape(cfg['calendar_id'])}\n"
        f"Напоминания за (мин): {cfg['reminder_minutes_before']}\n"
        f"Горизонт просмотра: {cfg['lookahead_hours']} ч.\n"
        f"Опрос календаря: каждые {cfg['poll_interval_seconds']} сек.\n"
        f"Часовой пояс: {escape(cfg['timezone'])}\n"
        f"Ежедневная сводка: в {escape(cfg['daily_digest_time'])}"
        + ADMIN_HELP_TEXT
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def set_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Использование: /set_calendar <id календаря или primary>"
        )
        return
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    try:
        runtime.set_calendar_id(context.args[0])
    except ConfigError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(f"Календарь обновлён: {runtime.calendar_id}")


async def set_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text("Использование: /set_reminders <60,10>")
        return
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    try:
        runtime.set_reminder_minutes_before(" ".join(context.args))
    except ConfigError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    minutes = ", ".join(str(m) for m in runtime.reminder_minutes_before)
    await update.effective_message.reply_text(f"Пороги напоминаний обновлены: {minutes}")


async def set_lookahead(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text("Использование: /set_lookahead <часы>")
        return
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    try:
        runtime.set_lookahead_hours(context.args[0])
    except ConfigError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(
        f"Горизонт просмотра обновлён: {runtime.lookahead_hours} ч."
    )


async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text("Использование: /set_interval <секунды>")
        return
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    try:
        new_interval = runtime.set_poll_interval_seconds(context.args[0])
    except ConfigError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    for job in context.job_queue.get_jobs_by_name("check_reminders"):
        job.schedule_removal()
    context.job_queue.run_repeating(
        check_reminders, interval=new_interval, first=5, name="check_reminders"
    )
    await update.effective_message.reply_text(f"Интервал опроса обновлён: {new_interval} сек.")


async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text("Использование: /set_timezone <Europe/Moscow>")
        return
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    try:
        runtime.set_timezone(context.args[0])
    except ConfigError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    _reschedule_daily_digest(context, runtime)
    await update.effective_message.reply_text(f"Часовой пояс обновлён: {runtime.timezone}")


async def set_digest_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Использование: /set_digest_time <ЧЧ:ММ>, например: 09:30"
        )
        return
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    try:
        runtime.set_daily_digest_time(context.args[0])
    except ConfigError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    _reschedule_daily_digest(context, runtime)
    await update.effective_message.reply_text(
        f"Время ежедневной сводки обновлено: {runtime.daily_digest_time}"
    )


def _reschedule_daily_digest(context: ContextTypes.DEFAULT_TYPE, runtime: RuntimeConfig) -> None:
    for job in context.job_queue.get_jobs_by_name("daily_digest"):
        job.schedule_removal()
    digest_time = runtime.daily_digest_time_obj.replace(tzinfo=ZoneInfo(runtime.timezone))
    context.job_queue.run_daily(send_daily_digest, time=digest_time, name="daily_digest")
