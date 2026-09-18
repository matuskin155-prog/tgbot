import asyncio
import logging

from telegram.ext import Application, CommandHandler

from . import handlers
from .config import load_settings
from .database import Database
from .google_calendar import GoogleCalendarClient
from .reminders import check_reminders

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main() -> None:
    # Python 3.14 больше не создаёт event loop неявно (PEP 719); python-telegram-bot
    # 21.x ещё полагается на старое поведение внутри run_polling(), поэтому создаём
    # и регистрируем loop вручную. Безопасно и для более старых версий Python.
    asyncio.set_event_loop(asyncio.new_event_loop())

    settings = load_settings()
    db = Database(settings.database_path)
    calendar = GoogleCalendarClient(
        service_account_file=settings.google_service_account_file,
        calendar_id=settings.google_calendar_id,
    )

    application = Application.builder().token(settings.telegram_token).build()
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db
    application.bot_data["calendar"] = calendar

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("subscribe", handlers.subscribe))
    application.add_handler(CommandHandler("unsubscribe", handlers.unsubscribe))
    application.add_handler(CommandHandler("status", handlers.status))
    application.add_handler(CommandHandler("today", handlers.today))
    application.add_handler(CommandHandler("upcoming", handlers.upcoming))

    application.job_queue.run_repeating(
        check_reminders,
        interval=settings.poll_interval_seconds,
        first=5,
        name="check_reminders",
    )

    logger.info("Бот запущен, опрашиваю календарь %s каждые %s сек.", settings.google_calendar_id, settings.poll_interval_seconds)
    application.run_polling(allowed_updates=[])


if __name__ == "__main__":
    main()
