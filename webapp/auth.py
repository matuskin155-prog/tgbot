import hashlib
import hmac
import json
import time
from typing import Any, Dict
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    """initData от Telegram WebApp отсутствует, повреждена или просрочена."""


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> Dict[str, Any]:
    """Проверяет подпись initData по алгоритму Telegram и возвращает распарсенные поля.

    См. https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
    """
    if not init_data:
        raise InitDataError("Нет initData — открывайте через кнопку в Telegram, не в браузере")

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            raise InitDataError("В initData нет подписи (hash)")

        data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        computed_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            raise InitDataError("Неверная подпись initData")

        auth_date = int(pairs.get("auth_date", "0"))
        if max_age_seconds and time.time() - auth_date > max_age_seconds:
            raise InitDataError("initData устарела, переоткройте приложение")

        result: Dict[str, Any] = dict(pairs)
        if "user" in result:
            result["user"] = json.loads(result["user"])
        return result
    except InitDataError:
        raise
    except (ValueError, json.JSONDecodeError) as exc:
        # parse_qsl(strict_parsing=True) и int(auth_date) кидают обычный
        # ValueError на любой кривой ввод — приводим его к одному типу
        # ошибки, который вызывающий код (webapp/server.py) умеет ловить.
        raise InitDataError("Не удалось разобрать initData") from exc
