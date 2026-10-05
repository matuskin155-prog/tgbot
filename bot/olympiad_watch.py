import hashlib
import logging
import re
from html import escape
from typing import List, Optional

import httpx
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .database import Database
from .olympiads import SOURCES, OlympiadSource

logger = logging.getLogger(__name__)

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _extract_text(html: str) -> str:
    html = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", html)
    return _WHITESPACE_RE.sub(" ", text).strip()


async def _fetch_hash(client: httpx.AsyncClient, url: str) -> Optional[str]:
    try:
        response = await client.get(url, timeout=20, follow_redirects=True)
        response.raise_for_status()
    except Exception:
        logger.warning("Не удалось проверить страницу олимпиады: %s", url, exc_info=True)
        return None
    text = _extract_text(response.text)
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def check_olympiad_sources(db: Database) -> List[OlympiadSource]:
    """Проверяет все источники, возвращает список тех, что изменились с прошлой проверки."""
    changed: List[OlympiadSource] = []

    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        for source in SOURCES:
            new_hash = await _fetch_hash(client, source.url)
            if new_hash is None:
                continue

            state = db.get_olympiad_state(source.key)
            old_hash = state[0] if state else None
            # При самой первой проверке источника просто запоминаем хэш,
            # не считаем это "изменением" — иначе при первом запуске
            # оповещение придёт сразу по всем 23 ссылкам.
            is_change = old_hash is not None and old_hash != new_hash
            db.save_olympiad_check(source.key, new_hash, is_change)
            if is_change:
                changed.append(source)

    return changed


async def check_olympiads_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Периодическая задача: проверяет страницы олимпиад и уведомляет администраторов."""
    settings = context.bot_data["settings"]
    if not settings.admin_chat_ids:
        return

    db: Database = context.bot_data["db"]
    try:
        changed = await check_olympiad_sources(db)
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
