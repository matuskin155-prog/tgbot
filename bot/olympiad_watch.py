import asyncio
import hashlib
import logging
import re
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
from .olympiads import SOURCES, OlympiadSource

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_PAGE_LOAD_TIMEOUT_SECONDS = 20


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


def _check_all_sync(
    db: Database, browser_executable_path: Optional[str]
) -> List[OlympiadSource]:
    """Синхронная часть — Selenium блокирующий, запускается в отдельном потоке."""
    changed: List[OlympiadSource] = []

    try:
        driver = _build_driver(browser_executable_path)
    except WebDriverException:
        logger.exception(
            "Не удалось запустить браузер для проверки олимпиад "
            "(проверьте BROWSER_EXECUTABLE_PATH и что браузер/драйвер установлены)"
        )
        return changed

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
    finally:
        driver.quit()

    return changed


async def check_olympiad_sources(
    db: Database, browser_executable_path: Optional[str] = None
) -> List[OlympiadSource]:
    """Проверяет все источники через headless-браузер, возвращает изменившиеся."""
    return await asyncio.to_thread(_check_all_sync, db, browser_executable_path)


async def check_olympiads_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Периодическая задача: проверяет страницы олимпиад и уведомляет администраторов."""
    settings = context.bot_data["settings"]
    if not settings.admin_chat_ids:
        return

    db: Database = context.bot_data["db"]
    try:
        changed = await check_olympiad_sources(db, settings.browser_executable_path)
    except Exception:
        logger.exception("Не удалось проверить страницы олимпиад")
        return

    if not changed:
        return

    lines = ["🔔 <b>Изменились страницы олимпиад — проверьте вручную:</b>"]
    for source in changed:
        lines.append(f'• <a href="{source.url}">{escape(source.name)}</a>')
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
