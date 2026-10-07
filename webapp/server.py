import asyncio
import logging
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from aiohttp import web

from bot.config import Settings, load_settings
from bot.database import Database
from bot.formatting import format_time_range, is_event_ongoing
from bot.google_calendar import GoogleCalendarClient
from bot.olympiad_watch import check_olympiad_sources
from bot.olympiads import SOURCES
from bot.runtime_config import ConfigError, Defaults, RuntimeConfig

from .auth import InitDataError, validate_init_data

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
DELETE_WINDOW_DAYS = 30


def _require_auth(request: web.Request) -> dict:
    settings: Settings = request.app["settings"]
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    try:
        data = validate_init_data(init_data, settings.telegram_token)
    except InitDataError as exc:
        raise web.HTTPUnauthorized(text=str(exc)) from exc

    user = data.get("user") or {}
    chat_id = user.get("id")
    if chat_id is None:
        raise web.HTTPUnauthorized(text="Нет данных пользователя в initData")
    return {"chat_id": chat_id, "is_admin": chat_id in settings.admin_chat_ids}


def _require_admin(auth: dict) -> None:
    if not auth["is_admin"]:
        raise web.HTTPForbidden(text="Доступно только администратору")


async def handle_state(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    db: Database = request.app["db"]
    runtime: RuntimeConfig = request.app["runtime_config"]

    payload = {
        "chat_id": auth["chat_id"],
        "is_admin": auth["is_admin"],
        "is_subscribed": db.is_subscribed(auth["chat_id"]),
    }
    if auth["is_admin"]:
        payload["config"] = runtime.as_dict()
    return web.json_response(payload)


async def handle_subscribe(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    db: Database = request.app["db"]
    db.add_subscriber(auth["chat_id"])
    return web.json_response({"ok": True})


async def handle_unsubscribe(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    db: Database = request.app["db"]
    db.remove_subscriber(auth["chat_id"])
    return web.json_response({"ok": True})


async def _events_payload(
    request: web.Request, hours: int, *, exclude_hidden_for: Optional[int] = None
) -> list:
    calendar: GoogleCalendarClient = request.app["calendar"]
    runtime: RuntimeConfig = request.app["runtime_config"]
    events = await asyncio.to_thread(calendar.get_upcoming_events, hours, runtime.calendar_id)
    tz = ZoneInfo(runtime.timezone)

    if exclude_hidden_for is not None:
        db: Database = request.app["db"]
        hidden = db.get_hidden_event_ids_for_chat(exclude_hidden_for)
        events = [e for e in events if e.id not in hidden]

    return [
        {
            "id": event.id,
            "summary": event.summary,
            "when": format_time_range(event, tz),
            "location": event.location,
            "date": event.start.astimezone(tz).date().isoformat(),
            "is_ongoing": is_event_ongoing(event),
            "all_day": event.all_day,
            "start_ts": event.start.isoformat(),
            "html_link": event.html_link,
            "olympiad_url": event.extended_properties.get("tgbot_olympiad_url"),
        }
        for event in events
    ]


async def handle_events_today(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    try:
        events = await _events_payload(request, 24, exclude_hidden_for=auth["chat_id"])
    except Exception:
        logger.exception("Не удалось получить события на сегодня")
        raise web.HTTPInternalServerError(text="Не получилось получить события из календаря")
    return web.json_response(events)


async def handle_events_upcoming(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    runtime: RuntimeConfig = request.app["runtime_config"]
    try:
        events = await _events_payload(
            request, runtime.lookahead_hours, exclude_hidden_for=auth["chat_id"]
        )
    except Exception:
        logger.exception("Не удалось получить ближайшие события")
        raise web.HTTPInternalServerError(text="Не получилось получить события из календаря")
    return web.json_response(events)


async def handle_events_deletable(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    _require_admin(auth)
    # Без exclude_hidden_for - админ должен видеть вообще все события,
    # включая те, что кто-то скрыл лично у себя, иначе не сможет ими
    # управлять (скрытие - личная настройка показа, не влияет на то, что
    # есть в самом календаре).
    try:
        events = await _events_payload(request, DELETE_WINDOW_DAYS * 24)
    except Exception:
        logger.exception("Не удалось получить события для удаления")
        raise web.HTTPInternalServerError(text="Не получилось получить события из календаря")
    return web.json_response(events)


async def handle_events_delete(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    _require_admin(auth)

    try:
        body = await request.json()
        event_id = body["event_id"]
    except Exception as exc:
        raise web.HTTPBadRequest(text="Нужно поле event_id") from exc

    calendar: GoogleCalendarClient = request.app["calendar"]
    runtime: RuntimeConfig = request.app["runtime_config"]
    try:
        await asyncio.to_thread(calendar.delete_event, event_id, runtime.calendar_id)
    except Exception as exc:
        logger.exception("Не удалось удалить событие %s через веб-приложение", event_id)
        raise web.HTTPInternalServerError(
            text="Не получилось удалить событие — проверьте права сервис-аккаунта"
        ) from exc

    return web.json_response({"ok": True})


async def handle_events_hide(request: web.Request) -> web.Response:
    # Доступно любому подписчику, не только админу - прячет событие только
    # у него самого (сам календарь не трогается, остальные подписчики
    # продолжают видеть событие и получать по нему напоминания).
    auth = _require_auth(request)
    try:
        body = await request.json()
        event_id = body["event_id"]
    except Exception as exc:
        raise web.HTTPBadRequest(text="Нужно поле event_id") from exc

    db: Database = request.app["db"]
    db.hide_event_for_chat(auth["chat_id"], event_id)
    return web.json_response({"ok": True})


async def handle_events_unhide(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    try:
        body = await request.json()
        event_id = body["event_id"]
    except Exception as exc:
        raise web.HTTPBadRequest(text="Нужно поле event_id") from exc

    db: Database = request.app["db"]
    db.unhide_event_for_chat(auth["chat_id"], event_id)
    return web.json_response({"ok": True})


async def handle_hidden_events(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    db: Database = request.app["db"]
    calendar: GoogleCalendarClient = request.app["calendar"]
    runtime: RuntimeConfig = request.app["runtime_config"]
    tz = ZoneInfo(runtime.timezone)

    hidden_ids = db.get_hidden_event_ids_for_chat(auth["chat_id"])
    result = []
    for event_id in sorted(hidden_ids):
        try:
            event = await asyncio.to_thread(calendar.get_event, event_id, runtime.calendar_id)
        except Exception:
            # Событие удалено из календаря целиком - смысла держать его
            # "скрытым" больше нет.
            db.unhide_event_for_chat(auth["chat_id"], event_id)
            continue
        result.append(
            {
                "id": event.id,
                "summary": event.summary,
                "when": format_time_range(event, tz),
            }
        )
    return web.json_response(result)


async def handle_olympiads(request: web.Request) -> web.Response:
    _require_auth(request)
    db: Database = request.app["db"]
    result = []
    for source in SOURCES:
        state = db.get_olympiad_state(source.key)
        result.append(
            {
                "key": source.key,
                "name": source.name,
                "url": source.url,
                "changed": bool(state and state[1]),
            }
        )
    return web.json_response(result)


async def handle_olympiads_check(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    _require_admin(auth)
    settings: Settings = request.app["settings"]
    db: Database = request.app["db"]
    calendar: GoogleCalendarClient = request.app["calendar"]
    runtime: RuntimeConfig = request.app["runtime_config"]
    try:
        result = await check_olympiad_sources(
            db, calendar, runtime.calendar_id, settings.browser_executable_path
        )
    except Exception as exc:
        logger.exception("Не удалось проверить страницы олимпиад")
        raise web.HTTPInternalServerError(text="Не получилось проверить страницы") from exc
    return web.json_response(
        {
            "changed": [{"name": s.name, "url": s.url} for s in result.changed],
            "added_events": [
                {
                    "name": e.source.name,
                    "url": e.source.url,
                    "is_new": e.is_new,
                    "start_date": e.start_date,
                    "end_date": e.end_date,
                    "label": e.label,
                }
                for e in result.added_events
            ],
        }
    )


async def handle_config_update(request: web.Request) -> web.Response:
    auth = _require_auth(request)
    _require_admin(auth)
    runtime: RuntimeConfig = request.app["runtime_config"]

    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Некорректный JSON") from exc

    setters = {
        "calendar_id": runtime.set_calendar_id,
        "reminder_minutes_before": runtime.set_reminder_minutes_before,
        "lookahead_hours": runtime.set_lookahead_hours,
        "poll_interval_seconds": runtime.set_poll_interval_seconds,
        "timezone": runtime.set_timezone,
        "daily_digest_time": runtime.set_daily_digest_time,
    }

    errors = {}
    for field, setter in setters.items():
        if field in body and body[field] != "":
            try:
                setter(str(body[field]))
            except ConfigError as exc:
                errors[field] = str(exc)

    if errors:
        return web.json_response({"ok": False, "errors": errors}, status=400)
    return web.json_response({"ok": True, "config": runtime.as_dict()})


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


def create_app() -> web.Application:
    settings = load_settings()
    db = Database(settings.database_path)
    calendar = GoogleCalendarClient(service_account_file=settings.google_service_account_file)
    runtime = RuntimeConfig(
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

    app = web.Application()
    app["settings"] = settings
    app["db"] = db
    app["calendar"] = calendar
    app["runtime_config"] = runtime

    app.router.add_get("/api/state", handle_state)
    app.router.add_post("/api/subscribe", handle_subscribe)
    app.router.add_post("/api/unsubscribe", handle_unsubscribe)
    app.router.add_get("/api/events/today", handle_events_today)
    app.router.add_get("/api/events/upcoming", handle_events_upcoming)
    app.router.add_get("/api/events/deletable", handle_events_deletable)
    app.router.add_post("/api/events/delete", handle_events_delete)
    app.router.add_post("/api/events/hide", handle_events_hide)
    app.router.add_post("/api/events/unhide", handle_events_unhide)
    app.router.add_get("/api/hidden_events", handle_hidden_events)
    app.router.add_get("/api/olympiads", handle_olympiads)
    app.router.add_post("/api/olympiads/check", handle_olympiads_check)
    app.router.add_post("/api/config", handle_config_update)
    app.router.add_static("/static/", STATIC_DIR, name="static")
    app.router.add_get("/", handle_index)
    return app


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    app = create_app()
    # Слушаем только localhost — наружу (443, HTTPS) смотрит Caddy или
    # Cloudflare Tunnel, который проксирует сюда (см. Caddyfile/
    # setup_cloudflare_tunnel.sh). Порт настраиваемый (WEBAPP_PORT в .env) —
    # на случай, если 8787 уже занят другим вашим проектом на этом сервере.
    settings: Settings = app["settings"]
    web.run_app(app, host="127.0.0.1", port=settings.webapp_port)


if __name__ == "__main__":
    main()
