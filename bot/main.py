import asyncio
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from telegram import BotCommand, BotCommandScopeChat, MenuButtonWebApp, WebAppInfo
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from . import handlers
from .config import Settings, load_settings
from .database import Database
from .digest import send_daily_digest
from .google_calendar import GoogleCalendarClient
from .olympiad_watch import check_olympiads_job
from .reminders import check_reminders
from .runtime_config import Defaults, RuntimeConfig
from .schedule_sync import sync_schedule_job

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

BASE_COMMANDS = [
    BotCommand("start", "Главное меню и кнопка приложения"),
    BotCommand("today", "События на сегодня"),
    BotCommand("upcoming", "Ближайшие события"),
    BotCommand("subscribe", "Включить напоминания"),
    BotCommand("unsubscribe", "Выключить напоминания"),
    BotCommand("status", "Текущие настройки и статус подписки"),
    BotCommand("olympiads", "Список отслеживаемых олимпиад"),
    BotCommand("whoami", "Узнать свой chat_id"),
    BotCommand("help", "Справка"),
]

ADMIN_EXTRA_COMMANDS = [
    BotCommand("config", "Текущие настройки (админ)"),
    BotCommand("set_calendar", "Сменить календарь"),
    BotCommand("set_reminders", "За сколько минут напоминать"),
    BotCommand("set_lookahead", "Горизонт просмотра"),
    BotCommand("set_interval", "Интервал опроса календаря"),
    BotCommand("set_timezone", "Часовой пояс"),
    BotCommand("set_digest_time", "Время ежедневной сводки"),
    BotCommand("delete_event", "Удалить событие из календаря"),
    BotCommand("check_olympiads", "Проверить олимпиады сейчас"),
]


_UI_SETUP_TIMEOUT = 15


async def _post_init(application: Application) -> None:
    # Настройка меню команд и кнопки мини-приложения — это некритичная
    # "косметика". PTB ждёт завершения post_init перед тем, как начать
    # реально обрабатывать сообщения, поэтому запускаем это фоновой
    # задачей: даже если Telegram API окажется медленным или недоступным,
    # это не должно задерживать (а тем более — навсегда блокировать) запуск
    # основного цикла бота. Раньше первый вызов ниже был вообще без
    # try/except и без таймаута — одно медленное зависание на старте
    # означало, что бот никогда не доходил до polling.
    asyncio.create_task(_configure_bot_ui(application))


async def _configure_bot_ui(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]

    try:
        await asyncio.wait_for(
            application.bot.set_my_commands(BASE_COMMANDS), timeout=_UI_SETUP_TIMEOUT
        )
    except (TelegramError, asyncio.TimeoutError):
        logger.warning("Не удалось настроить базовое меню команд", exc_info=True)

    for admin_id in settings.admin_chat_ids:
        try:
            await asyncio.wait_for(
                application.bot.set_my_commands(
                    BASE_COMMANDS + ADMIN_EXTRA_COMMANDS,
                    scope=BotCommandScopeChat(chat_id=admin_id),
                ),
                timeout=_UI_SETUP_TIMEOUT,
            )
        except (TelegramError, asyncio.TimeoutError):
            logger.warning("Не удалось настроить меню команд для чата %s", admin_id)

    if settings.webapp_url:
        try:
            await asyncio.wait_for(
                application.bot.set_chat_menu_button(
                    menu_button=MenuButtonWebApp(
                        text="Открыть", web_app=WebAppInfo(url=settings.webapp_url)
                    )
                ),
                timeout=_UI_SETUP_TIMEOUT,
            )
        except (TelegramError, asyncio.TimeoutError):
            logger.warning("Не удалось установить кнопку мини-приложения в меню чата")


def main() -> None:
    # Python 3.14 больше не создаёт event loop неявно (PEP 719); python-telegram-bot
    # 21.x ещё полагается на старое поведение внутри run_polling(), поэтому создаём
    # и регистрируем loop вручную. Безопасно и для более старых версий Python.
    asyncio.set_event_loop(asyncio.new_event_loop())

    settings = load_settings()
    db = Database(settings.database_path)
    calendar = GoogleCalendarClient(service_account_file=settings.google_service_account_file)
    runtime_config = RuntimeConfig(
        db,
        Defaults(
            calendar_id=settings.google_calendar_id,
            reminder_minutes_before=settings.reminder_minutes_before,
            poll_interval_seconds=settings.poll_interval_seconds,
            lookahead_hours=settings.lookahead_hours,
            timezone=settings.timezone,
            daily_digest_time=settings.daily_digest_time,
        ),
    )

    application = (
        Application.builder().token(settings.telegram_token).post_init(_post_init).build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db
    application.bot_data["calendar"] = calendar
    application.bot_data["runtime_config"] = runtime_config

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("whoami", handlers.whoami))
    application.add_handler(CommandHandler("subscribe", handlers.subscribe))
    application.add_handler(CommandHandler("unsubscribe", handlers.unsubscribe))
    application.add_handler(CommandHandler("status", handlers.status))
    application.add_handler(CommandHandler("today", handlers.today))
    application.add_handler(CommandHandler("upcoming", handlers.upcoming))
    application.add_handler(CommandHandler("config", handlers.config_command))
    application.add_handler(CommandHandler("set_calendar", handlers.set_calendar))
    application.add_handler(CommandHandler("set_reminders", handlers.set_reminders))
    application.add_handler(CommandHandler("set_lookahead", handlers.set_lookahead))
    application.add_handler(CommandHandler("set_interval", handlers.set_interval))
    application.add_handler(CommandHandler("set_timezone", handlers.set_timezone))
    application.add_handler(CommandHandler("set_digest_time", handlers.set_digest_time))
    application.add_handler(CommandHandler("delete_event", handlers.delete_event_command))
    application.add_handler(CommandHandler("olympiads", handlers.olympiads_command))
    application.add_handler(CommandHandler("check_olympiads", handlers.check_olympiads_command))
    application.add_handler(CallbackQueryHandler(handlers.handle_delete_pick, pattern=r"^delpick:"))
    application.add_handler(
        CallbackQueryHandler(handlers.handle_delete_confirm, pattern=r"^delconfirm:")
    )
    application.add_handler(CallbackQueryHandler(handlers.handle_delete_cancel, pattern=r"^delcancel$"))

    application.job_queue.run_repeating(
        check_reminders,
        interval=runtime_config.poll_interval_seconds,
        first=5,
        name="check_reminders",
    )
    application.bot_data["_last_interval"] = runtime_config.poll_interval_seconds

    digest_time = runtime_config.daily_digest_time_obj.replace(
        tzinfo=ZoneInfo(runtime_config.timezone)
    )
    application.job_queue.run_daily(send_daily_digest, time=digest_time, name="daily_digest")
    application.bot_data["_last_digest_key"] = (
        runtime_config.daily_digest_time,
        runtime_config.timezone,
    )

    application.job_queue.run_repeating(
        check_olympiads_job,
        interval=timedelta(hours=24),
        first=60,
        name="check_olympiads",
    )

    application.job_queue.run_repeating(
        sync_schedule_job,
        interval=30,
        first=30,
        name="sync_schedule",
    )

    logger.info(
        "Бот запущен, опрашиваю календарь %s каждые %s сек., ежедневная сводка в %s (%s).",
        runtime_config.calendar_id,
        runtime_config.poll_interval_seconds,
        runtime_config.daily_digest_time,
        runtime_config.timezone,
    )
    application.run_polling(allowed_updates=[])


if __name__ == "__main__":
    main()
