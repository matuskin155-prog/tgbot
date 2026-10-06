import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from typing import List, Optional

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .database import Database
from .google_calendar import GoogleCalendarClient
from .olympiad_dates import extract_candidate_dates
from .olympiads import SOURCES, OlympiadSource

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_PAGE_LOAD_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class AddedOlympiadEvent:
    source: OlympiadSource
    is_new: bool
    start_date: str
    end_date: str
    context: str


def _event_id(source_key: str, index: int) -> str:
    # Google Calendar ограничивает id событий символами base32hex
    # (строчные a-v и цифры) - hex-дайджест этому требованию уже
    # удовлетворяет, добавляем префикс только для читаемости в логах.
    digest = hashlib.sha256(f"olympiad:{source_key}:{index}".encode("utf-8")).hexdigest()
    return f"tgbot{digest}"


def _sync_calendar_events(
    db: Database,
    calendar: GoogleCalendarClient,
    calendar_id: str,
    source: OlympiadSource,
    text: str,
) -> List[AddedOlympiadEvent]:
    """Ищет в тексте страницы даты и заводит/обновляет по ним all-day
    события в календаре. Возвращает только те, что добавились впервые или
    у которых изменились даты - для уведомления админов (неизменные события
    не беспокоят повторно каждую проверку)."""
    added: List[AddedOlympiadEvent] = []

    for candidate in extract_candidate_dates(text):
        event_id = _event_id(source.key, candidate.index)
        previous = db.get_olympiad_event_dates(event_id)
        new_start = candidate.start.isoformat()
        new_end = candidate.end.isoformat()

        is_new = previous is None
        is_changed = previous is not None and previous != (new_start, new_end)
        if not (is_new or is_changed):
            continue

        description = (
            f"⚠️ Дата определена автоматически с сайта олимпиады, сверьте: {source.url}\n\n"
            f"Контекст со страницы: «{candidate.context}»"
        )
        try:
            calendar.upsert_event(
                event_id=event_id,
                calendar_id=calendar_id,
                summary=f"📅 {source.name} (авто)",
                description=description,
                start_date=candidate.start,
                end_date=candidate.end,
            )
        except Exception:
            logger.exception(
                "Не удалось добавить/обновить событие календаря для олимпиады %s", source.key
            )
            continue

        db.save_olympiad_event(event_id, source.key, new_start, new_end)
        added.append(
            AddedOlympiadEvent(
                source=source,
                is_new=is_new,
                start_date=new_start,
                end_date=new_end,
                context=candidate.context,
            )
        )

    return added


def _build_driver(browser_executable_path: Optional[str]) -> webdriver.Chrome:
    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    if browser_executable_path:
        options.binary_location = browser_executable_path

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(_PAGE_LOAD_TIMEOUT_SECONDS)
    return driver


def _fetch_rendered_text(driver: webdriver.Chrome, url: str) -> Optional[str]:
    try:
        driver.get(url)
        text = driver.find_element(By.TAG_NAME, "body").text
    except WebDriverException:
        logger.warning("Не удалось открыть страницу олимпиады: %s", url, exc_info=True)
        return None
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None


@dataclass(frozen=True)
class _CheckResult:
    changed: List[OlympiadSource]
    added_events: List[AddedOlympiadEvent]


def _check_all_sync(
    db: Database,
    calendar: GoogleCalendarClient,
    calendar_id: str,
    browser_executable_path: Optional[str],
) -> _CheckResult:
    """Синхронная часть — Selenium блокирующий, запускается в отдельном потоке."""
    changed: List[OlympiadSource] = []
    added_events: List[AddedOlympiadEvent] = []

    try:
        driver = _build_driver(browser_executable_path)
    except WebDriverException:
        logger.exception(
            "Не удалось запустить браузер для проверки олимпиад "
            "(проверьте BROWSER_EXECUTABLE_PATH и что браузер/драйвер установлены)"
        )
        return _CheckResult(changed, added_events)

    try:
        for source in SOURCES:
            text = _fetch_rendered_text(driver, source.url)
            if text is None:
                continue
            new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

            state = db.get_olympiad_state(source.key)
            old_hash = state[0] if state else None
            # При самой первой проверке источника просто запоминаем хэш,
            # не считаем это "изменением" — иначе при первом запуске
            # оповещение придёт сразу по всем 23 ссылкам.
            is_change = old_hash is not None and old_hash != new_hash
            db.save_olympiad_check(source.key, new_hash, is_change)
            if is_change:
                changed.append(source)

            added_events.extend(
                _sync_calendar_events(db, calendar, calendar_id, source, text)
            )
    finally:
        driver.quit()

    return _CheckResult(changed, added_events)


async def check_olympiad_sources(
    db: Database,
    calendar: GoogleCalendarClient,
    calendar_id: str,
    browser_executable_path: Optional[str] = None,
) -> _CheckResult:
    """Проверяет все источники через headless-браузер: возвращает изменившиеся
    страницы и события, заведённые/обновлённые в календаре по найденным датам."""
    return await asyncio.to_thread(
        _check_all_sync, db, calendar, calendar_id, browser_executable_path
    )


async def check_olympiads_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Периодическая задача: проверяет страницы олимпиад, заводит события по
    найденным датам в календаре и уведомляет администраторов."""
    settings = context.bot_data["settings"]
    if not settings.admin_chat_ids:
        return

    db: Database = context.bot_data["db"]
    calendar: GoogleCalendarClient = context.bot_data["calendar"]
    runtime = context.bot_data["runtime_config"]
    try:
        result = await check_olympiad_sources(
            db, calendar, runtime.calendar_id, settings.browser_executable_path
        )
    except Exception:
        logger.exception("Не удалось проверить страницы олимпиад")
        return

    lines = []
    if result.added_events:
        lines.append("📅 <b>Автоматически добавлены/обновлены в календаре:</b>")
        for event in result.added_events:
            mark = "новое" if event.is_new else "дата изменилась"
            # end_date исключительный (такой, какой Google Calendar хранит для
            # all-day событий) - для однодневного события он всегда на 1 день
            # позже start_date, поэтому для показа переводим обратно во
            # включительный и сравниваем уже его.
            inclusive_end = date.fromisoformat(event.end_date) - timedelta(days=1)
            date_range = event.start_date
            if inclusive_end.isoformat() != event.start_date:
                date_range += f" – {inclusive_end.isoformat()}"
            lines.append(
                f'• <a href="{event.source.url}">{escape(event.source.name)}</a> '
                f"({mark}): {date_range}"
            )
        lines.append("Даты определены автоматически по тексту страницы — сверьте на сайте.")

    if result.changed:
        if lines:
            lines.append("")
        lines.append("🔔 <b>Изменились страницы олимпиад — проверьте вручную:</b>")
        for source in result.changed:
            lines.append(f'• <a href="{source.url}">{escape(source.name)}</a>')

    if not lines:
        return

    text = "\n".join(lines)

    for chat_id in settings.admin_chat_ids:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramError:
            logger.exception("Не удалось отправить уведомление об олимпиадах в чат %s", chat_id)
