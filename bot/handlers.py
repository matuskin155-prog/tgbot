import asyncio
import logging
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .config import Settings
from .database import Database
from .digest import send_daily_digest
from .formatting import format_event_line, format_time_range
from .google_calendar import GoogleCalendarClient
from .olympiads import SOURCES
from .reminders import check_reminders
from .runtime_config import ConfigError, RuntimeConfig

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Привет! Я присылаю напоминания о событиях из общего Google Calendar — "
    "подписаться на них может любой, кто напишет мне /subscribe.\n\n"
    "Нажмите кнопку ниже, чтобы открыть удобное приложение с календарём, "
    "олимпиадами и настройками — или используйте команды:\n"
    "/subscribe — включить напоминания в этом чате\n"
    "/unsubscribe — выключить напоминания\n"
    "/today — события на ближайшие 24 часа\n"
    "/upcoming — все события в пределах горизонта просмотра\n"
    "/hide_event — скрыть событие только у себя (остальных не затронет)\n"
    "/hidden_events — вернуть то, что вы скрыли\n"
    "/status — текущие настройки\n"
    "/whoami — узнать свой chat_id\n"
    "/olympiads — список известных олимпиад\n\n"
    "Каждый день в заданное время я также присылаю сводку событий на сегодня "
    "всем, кто подписан (/status покажет, во сколько)."
)

ADMIN_HELP_TEXT = (
    "\n\nКоманды администратора (только для ADMIN_CHAT_IDS):\n"
    "/config — показать текущие настройки\n"
    "/set_calendar <id> — сменить календарь\n"
    "/set_reminders <60,10> — за сколько минут напоминать\n"
    "/set_olympiad_deadlines <7,1> — за сколько дней напоминать о закрытии "
    "регистрации/отборочного этапа олимпиады\n"
    "/set_lookahead <часы> — горизонт просмотра\n"
    "/set_interval <секунды> — как часто опрашивать календарь\n"
    "/set_timezone <Europe/Moscow> — часовой пояс\n"
    "/set_digest_time <ЧЧ:ММ> — время ежедневной сводки\n"
    "/delete_event — удалить событие из календаря"
)

DELETE_WINDOW_DAYS = 30
DELETE_LIST_LIMIT = 30


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    text = WELCOME_TEXT
    if _is_admin(update, context):
        text += ADMIN_HELP_TEXT

    keyboard = None
    if settings.webapp_url:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📱 Открыть приложение", web_app=WebAppInfo(url=settings.webapp_url))]]
        )
    await update.effective_message.reply_text(text, reply_markup=keyboard)


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
    db: Database = context.bot_data["db"]

    try:
        events = await asyncio.to_thread(calendar.get_upcoming_events, hours, runtime.calendar_id)
    except Exception:
        logger.exception("Не удалось получить события для команды %s", title)
        await update.effective_message.reply_text("Не получилось получить события из календаря 😕")
        return

    # Пользователь мог лично скрыть у себя часть событий - ему их не
    # показываем, остальным подписчикам они видны как обычно.
    hidden = db.get_hidden_event_ids_for_chat(update.effective_chat.id)
    events = [e for e in events if e.id not in hidden]

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
        f"Дедлайны олимпиад за (дней): {cfg['olympiad_deadline_days_before']}\n"
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


async def set_olympiad_deadlines(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text("Использование: /set_olympiad_deadlines <7,1>")
        return
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    try:
        runtime.set_olympiad_deadline_days_before(" ".join(context.args))
    except ConfigError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    days = ", ".join(str(d) for d in runtime.olympiad_deadline_days_before)
    await update.effective_message.reply_text(f"Пороги дедлайнов олимпиад обновлены: {days}")


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
    # sync_schedule_job сверяет текущий интервал именно с этим значением —
    # не обновив его, она решит, что настройка разошлась с базой, и через
    # ≤30 сек пересоздаст эту же задачу ещё раз.
    context.bot_data["_last_interval"] = new_interval
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
    # См. комментарий в set_interval() - то же самое для sync_schedule_job
    # и ключа сводки (иначе она пересоздаст эту же задачу ещё раз сама).
    context.bot_data["_last_digest_key"] = (runtime.daily_digest_time, runtime.timezone)


# --- Удаление события из календаря (с подтверждением через кнопки) ---


async def delete_event_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return

    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]

    try:
        events = await asyncio.to_thread(
            calendar.get_upcoming_events, DELETE_WINDOW_DAYS * 24, runtime.calendar_id
        )
    except Exception:
        logger.exception("Не удалось получить события для удаления")
        await update.effective_message.reply_text("Не получилось получить события из календаря 😕")
        return

    if not events:
        await update.effective_message.reply_text(
            f"Событий в ближайшие {DELETE_WINDOW_DAYS} дней не найдено."
        )
        return

    tz = ZoneInfo(runtime.timezone)
    buttons = []
    for event in events[:DELETE_LIST_LIMIT]:
        label = f"{format_time_range(event, tz)} — {event.summary}"
        if len(label) > 60:
            label = label[:57] + "..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"delpick:{event.id}")])

    text = "Выберите событие, которое нужно удалить из календаря:"
    if len(events) > DELETE_LIST_LIMIT:
        text += f"\n(показаны первые {DELETE_LIST_LIMIT} из {len(events)})"

    await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def handle_delete_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not await _require_admin(update, context):
        return

    event_id = query.data.split(":", 1)[1]
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]

    try:
        event = await asyncio.to_thread(calendar.get_event, event_id, runtime.calendar_id)
    except Exception:
        logger.exception("Не удалось получить событие %s для подтверждения удаления", event_id)
        await query.edit_message_text("Не получилось найти это событие — возможно, оно уже удалено.")
        return

    tz = ZoneInfo(runtime.timezone)
    when = format_time_range(event, tz)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"delconfirm:{event_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data="delcancel"),
            ]
        ]
    )
    await query.edit_message_text(
        f"Удалить это событие из календаря?\n\n<b>{escape(event.summary)}</b>\n🕒 {when}",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not await _require_admin(update, context):
        return

    event_id = query.data.split(":", 1)[1]
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]

    try:
        await asyncio.to_thread(calendar.delete_event, event_id, runtime.calendar_id)
    except Exception:
        logger.exception("Не удалось удалить событие %s", event_id)
        await query.edit_message_text(
            "Не получилось удалить событие 😕\n"
            "Проверьте, что сервис-аккаунту выдан доступ «Делать изменения в "
            "мероприятиях» в настройках календаря (см. README)."
        )
        return

    await query.edit_message_text("Событие удалено из календаря ✅")


async def handle_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отменено, событие не тронуто.")


# --- Скрыть событие только у себя (доступно всем, не только админу) ---
# В отличие от /delete_event, это не трогает сам календарь - остальные
# подписчики продолжают видеть событие и получать по нему напоминания.

HIDE_WINDOW_DAYS = 30
HIDE_LIST_LIMIT = 30


async def hide_event_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    db: Database = context.bot_data["db"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    chat_id = update.effective_chat.id

    try:
        events = await asyncio.to_thread(
            calendar.get_upcoming_events, HIDE_WINDOW_DAYS * 24, runtime.calendar_id
        )
    except Exception:
        logger.exception("Не удалось получить события для скрытия")
        await update.effective_message.reply_text("Не получилось получить события из календаря 😕")
        return

    hidden = db.get_hidden_event_ids_for_chat(chat_id)
    events = [e for e in events if e.id not in hidden]
    if not events:
        await update.effective_message.reply_text(
            f"Событий в ближайшие {HIDE_WINDOW_DAYS} дней не найдено (или все уже скрыты)."
        )
        return

    tz = ZoneInfo(runtime.timezone)
    buttons = []
    for event in events[:HIDE_LIST_LIMIT]:
        label = f"{format_time_range(event, tz)} — {event.summary}"
        if len(label) > 60:
            label = label[:57] + "..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"hidepick:{event.id}")])

    text = "Выберите событие, которое нужно скрыть только у себя:"
    if len(events) > HIDE_LIST_LIMIT:
        text += f"\n(показаны первые {HIDE_LIST_LIMIT} из {len(events)})"

    await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def handle_hide_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    event_id = query.data.split(":", 1)[1]
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]

    try:
        event = await asyncio.to_thread(calendar.get_event, event_id, runtime.calendar_id)
    except Exception:
        logger.exception("Не удалось получить событие %s для подтверждения скрытия", event_id)
        await query.edit_message_text("Не получилось найти это событие — возможно, оно уже удалено.")
        return

    tz = ZoneInfo(runtime.timezone)
    when = format_time_range(event, tz)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Да, скрыть у себя", callback_data=f"hideconfirm:{event_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data="hidecancel"),
            ]
        ]
    )
    await query.edit_message_text(
        "Скрыть это событие только у вас? Остальные подписчики продолжат его "
        f"видеть и получать по нему напоминания.\n\n<b>{escape(event.summary)}</b>\n🕒 {when}",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_hide_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    db: Database = context.bot_data["db"]
    event_id = query.data.split(":", 1)[1]
    db.hide_event_for_chat(update.effective_chat.id, event_id)
    await query.edit_message_text(
        "Скрыто ✅ Больше не будет показываться у вас и не будет по нему напоминаний.\n"
        "Вернуть обратно можно командой /hidden_events"
    )


async def handle_hide_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отменено, событие не тронуто.")


async def hidden_events_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список событий, скрытых лично этим пользователем, с кнопками вернуть."""
    db: Database = context.bot_data["db"]
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    runtime: RuntimeConfig = context.bot_data["runtime_config"]
    chat_id = update.effective_chat.id

    hidden_ids = db.get_hidden_event_ids_for_chat(chat_id)
    if not hidden_ids:
        await update.effective_message.reply_text("У вас нет скрытых событий.")
        return

    tz = ZoneInfo(runtime.timezone)
    buttons = []
    missing = 0
    for event_id in sorted(hidden_ids):
        try:
            event = await asyncio.to_thread(calendar.get_event, event_id, runtime.calendar_id)
        except Exception:
            # Событие могли удалить из календаря целиком - смысла держать
            # его "скрытым" больше нет, просто убираем запись.
            db.unhide_event_for_chat(chat_id, event_id)
            missing += 1
            continue
        label = f"{format_time_range(event, tz)} — {event.summary}"
        if len(label) > 60:
            label = label[:57] + "..."
        buttons.append([InlineKeyboardButton(f"↩️ {label}", callback_data=f"unhide:{event_id}")])

    if not buttons:
        await update.effective_message.reply_text("У вас нет скрытых событий.")
        return

    text = "Ваши скрытые события — нажмите, чтобы вернуть:"
    if missing:
        text += f"\n({missing} уже не существует в календаре, убраны из списка)"
    await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def handle_unhide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    db: Database = context.bot_data["db"]
    event_id = query.data.split(":", 1)[1]
    db.unhide_event_for_chat(update.effective_chat.id, event_id)
    await query.edit_message_text("Возвращено — снова будет показываться и напоминать.")


# --- Справочник сайтов олимпиад ---


async def olympiads_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["<b>Известные олимпиады:</b>"]
    for source in SOURCES:
        lines.append(f'• <a href="{source.url}">{escape(source.name)}</a>')
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )
