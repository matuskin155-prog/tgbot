from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

from .digest import send_daily_digest
from .reminders import check_reminders
from .runtime_config import RuntimeConfig


async def sync_schedule_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подхватывает смену интервала опроса / времени сводки, если их поменяли
    не командой бота, а через веб-приложение (отдельный процесс, у него нет
    доступа к job_queue этого процесса) — сверяет с базой и пересобирает
    задачи, если что-то расходится."""
    runtime: RuntimeConfig = context.bot_data["runtime_config"]

    if context.bot_data.get("_last_interval") != runtime.poll_interval_seconds:
        for job in context.job_queue.get_jobs_by_name("check_reminders"):
            job.schedule_removal()
        context.job_queue.run_repeating(
            check_reminders, interval=runtime.poll_interval_seconds, first=1, name="check_reminders"
        )
        context.bot_data["_last_interval"] = runtime.poll_interval_seconds

    digest_key = (runtime.daily_digest_time, runtime.timezone)
    if context.bot_data.get("_last_digest_key") != digest_key:
        for job in context.job_queue.get_jobs_by_name("daily_digest"):
            job.schedule_removal()
        digest_time = runtime.daily_digest_time_obj.replace(tzinfo=ZoneInfo(runtime.timezone))
        context.job_queue.run_daily(send_daily_digest, time=digest_time, name="daily_digest")
        context.bot_data["_last_digest_key"] = digest_key
