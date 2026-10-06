#!/usr/bin/env bash
set -euo pipefail

# Поднимает Cloudflare WARP в режиме локального SOCKS5-прокси и прописывает
# TELEGRAM_PROXY_URL в .env — это самый частый способ обойти блокировку
# Telegram на уровне провайдера/хостинга (см. README.md, раздел
# «Если бот не отвечает: сервер не может достучаться до Telegram»).
#
# Запускать на самом сервере, от root, из папки проекта:
#   sudo bash setup_warp_proxy.sh
#
# ВАЖНО: WARP сам подключается к Cloudflare по UDP (порт 2408). Если
# провайдер режет и его — одного этого скрипта не хватит, тогда нужен
# zapret (см. README, раздел про zapret, который идёт сразу после
# результатов этого скрипта).
#
# Команды warp-cli у разных версий клиента отличаются (старые — плоские:
# `register`, `set-mode proxy`; новые — сгруппированные: `registration new`,
# `mode proxy`). Скрипт пробует оба варианта, но если ваша версия окажется
# третьей — смотрите `warp-cli --help` и правьте команды ниже.

if [[ "${EUID}" -ne 0 ]]; then
    echo "Запустите этот скрипт от root: sudo bash setup_warp_proxy.sh" >&2
    exit 1
fi

PROXY_PORT="${WARP_PROXY_PORT:-40000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
# socks5h (а не socks5) — чтобы DNS-запрос к api.telegram.org тоже шёл через
# WARP, а не через DNS самого сервера (он тоже может быть подделан/заблокирован
# у провайдера отдельно от самого соединения — обычный приём блокировок).
PROXY_URL="socks5h://127.0.0.1:${PROXY_PORT}"

try_warp() {
    echo "    > warp-cli $*"
    warp-cli --accept-tos "$@"
}

echo "==> Устанавливаю Cloudflare WARP..."
if ! command -v warp-cli >/dev/null 2>&1; then
    curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
        | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/cloudflare-client.list
    apt-get update
    apt-get install -y cloudflare-warp
else
    echo "    cloudflare-warp уже установлен."
fi

echo "==> Запускаю службу warp-svc..."
systemctl enable --now warp-svc
sleep 3

echo "==> Регистрирую клиента WARP (если ещё не зарегистрирован)..."
try_warp registration new || try_warp register || true

echo "==> Включаю режим локального SOCKS5-прокси..."
try_warp mode proxy || try_warp set-mode proxy || true
try_warp proxy port "${PROXY_PORT}" 2>/dev/null || true

echo "==> Подключаюсь..."
try_warp connect || true
sleep 2

echo "==> Статус WARP:"
try_warp status || true

echo
echo "==> Проверяю, отвечает ли Telegram через этот прокси..."
if curl -s --max-time 15 --proxy "${PROXY_URL}" https://api.telegram.org/ -o /dev/null; then
    echo "    OK: Telegram через WARP отвечает."
    WARP_WORKS=1
else
    echo "    ВНИМАНИЕ: Telegram не ответил даже через WARP." >&2
    echo "    Похоже, провайдер блокирует и сам WARP (UDP 2408) — переходите" >&2
    echo "    к разделу про zapret в README.md: он должен пробить именно этот" >&2
    echo "    момент (подключение WARP), дальше WARP сам доедет до Telegram." >&2
    WARP_WORKS=0
fi

# .env правим только если WARP реально помог — иначе лучше оставить
# TELEGRAM_PROXY_URL пустым, чем прописать нерабочий прокси (деплой-скрипт
# по этому же признаку понимает, помог ли WARP, см. deploy.sh).
if [[ "${WARP_WORKS}" -eq 1 ]]; then
    if [[ ! -f "${ENV_FILE}" ]]; then
        echo >&2
        echo "Не найден .env рядом со скриптом ($ENV_FILE) — впишите вручную:" >&2
        echo "TELEGRAM_PROXY_URL=${PROXY_URL}" >&2
        exit 1
    fi

    if grep -q '^TELEGRAM_PROXY_URL=' "${ENV_FILE}"; then
        sed -i "s|^TELEGRAM_PROXY_URL=.*|TELEGRAM_PROXY_URL=${PROXY_URL}|" "${ENV_FILE}"
    else
        echo "TELEGRAM_PROXY_URL=${PROXY_URL}" >> "${ENV_FILE}"
    fi
    echo
    echo "==> .env обновлён: TELEGRAM_PROXY_URL=${PROXY_URL}"

    if systemctl list-unit-files | grep -q '^tgbot.service'; then
        echo "==> Перезапускаю tgbot.service..."
        systemctl restart tgbot.service
    else
        echo "==> Служба tgbot.service не найдена — перезапустите бота вручную."
    fi

    echo
    echo "Готово. Проверьте бота в Telegram (/start)."
else
    echo
    echo "WARP настроен, но Telegram через него не отвечает — .env не трогаю."
    echo "См. раздел про zapret в README.md."
fi
