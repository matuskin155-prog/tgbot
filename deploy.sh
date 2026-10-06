#!/usr/bin/env bash
# Разворачивает бота на Debian/Ubuntu-сервере одной командой:
# системные пакеты -> venv -> зависимости -> systemd-автозапуск ->
# проверка связи с Telegram (с авто-обходом через Cloudflare WARP,
# если провайдер блокирует Telegram напрямую) -> Mini App.
#
# Секреты (.env с токеном, service_account.json) скрипт сам не создаёт —
# при их отсутствии он остановится и скажет, что положить и куда.
#
# Запускать из папки с кодом бота: sudo bash deploy.sh

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Запустите от root: sudo bash deploy.sh"
    exit 1
fi

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo "=== 1/5: системные пакеты (python3, venv, Google Chrome) ==="
apt-get update
apt-get install -y python3 python3-venv python3-pip wget

# На Ubuntu пакет chromium — это пересадочная заглушка на snap, и без
# рабочего snapd (обычная ситуация на серверах) браузер фактически не
# ставится, хотя apt отчитывается об успехе. Google Chrome ставится как
# обычный .deb и работает одинаково надёжно на Debian и Ubuntu.
if [ ! -x /usr/bin/google-chrome ]; then
    TMP_DEB="$(mktemp --suffix=.deb)"
    wget -q -O "$TMP_DEB" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get install -y "$TMP_DEB"
    rm -f "$TMP_DEB"
fi

echo "=== 2/5: виртуальное окружение и зависимости ==="
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo "Создан файл .env — откройте его (nano .env), впишите TELEGRAM_BOT_TOKEN,"
    echo "положите рядом service_account.json и запустите этот скрипт ещё раз."
    exit 0
fi

if [ ! -f service_account.json ]; then
    echo
    echo "Не найден service_account.json в $PROJECT_DIR — положите его сюда"
    echo "(через WinSCP) и запустите скрипт ещё раз."
    exit 1
fi

# Всегда указываем на Chrome, который только что поставили выше (а не
# только при первом запуске) — если тут раньше оказался путь к
# несработавшему chromium, этот прогон его исправит.
BROWSER_PATH="$(command -v google-chrome || true)"
if [ -n "$BROWSER_PATH" ]; then
    if grep -q "^BROWSER_EXECUTABLE_PATH=.*$" .env 2>/dev/null; then
        sed -i "s|^BROWSER_EXECUTABLE_PATH=.*$|BROWSER_EXECUTABLE_PATH=$BROWSER_PATH|" .env
    else
        echo "BROWSER_EXECUTABLE_PATH=$BROWSER_PATH" >> .env
    fi
fi

echo "=== 3/5: systemd-автозапуск бота ==="
cat > /etc/systemd/system/tgbot.service <<EOF
[Unit]
Description=Telegram Google Calendar reminder bot
After=network.target

[Service]
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/.venv/bin/python -m bot.main
EnvironmentFile=$PROJECT_DIR/.env
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable tgbot
systemctl restart tgbot

echo "=== 4/5: проверка связи с Telegram ==="
EXISTING_PROXY="$(grep -E '^TELEGRAM_PROXY_URL=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
if [ -n "$EXISTING_PROXY" ]; then
    echo "TELEGRAM_PROXY_URL уже задан в .env — пропускаю проверку."
elif curl -sf --max-time 10 https://api.telegram.org/ -o /dev/null; then
    echo "Telegram доступен напрямую — прокси не нужен."
else
    echo "Сервер не достучался до Telegram напрямую (бывает у некоторых"
    echo "хостингов/регионов — не связано с кодом бота). Пробую автоматически"
    echo "обойти через Cloudflare WARP..."
    bash "$PROJECT_DIR/setup_warp_proxy.sh" || true

    NEW_PROXY="$(grep -E '^TELEGRAM_PROXY_URL=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
    if [ -n "$NEW_PROXY" ]; then
        echo "Cloudflare WARP помог, бот переключён на $NEW_PROXY."
    else
        echo "Cloudflare WARP не помог (провайдер блокирует и его) — нужен"
        echo "zapret, см. README.md, раздел «Если блокируют и WARP: zapret»."
    fi
fi

echo "=== 5/5: Mini App (веб-приложение) ==="
WEBAPP_DOMAIN="$(grep -E '^WEBAPP_DOMAIN=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
WEBAPP_VIA_TUNNEL="$(grep -E '^WEBAPP_VIA_CLOUDFLARE_TUNNEL=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
if [ -n "$WEBAPP_DOMAIN" ]; then
    apt-get install -y caddy

    cat > /etc/caddy/Caddyfile <<EOF
$WEBAPP_DOMAIN {
    reverse_proxy 127.0.0.1:8787
}
EOF
    systemctl enable caddy
    systemctl restart caddy

    if grep -q "^WEBAPP_URL=.*$" .env 2>/dev/null; then
        sed -i "s|^WEBAPP_URL=.*$|WEBAPP_URL=https://$WEBAPP_DOMAIN|" .env
    else
        echo "WEBAPP_URL=https://$WEBAPP_DOMAIN" >> .env
    fi

    cat > /etc/systemd/system/tgbot-webapp.service <<EOF
[Unit]
Description=Telegram bot Mini App web server
After=network.target

[Service]
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/.venv/bin/python -m webapp.server
EnvironmentFile=$PROJECT_DIR/.env
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable tgbot-webapp
    systemctl restart tgbot-webapp

    echo "Mini App настроен на https://$WEBAPP_DOMAIN"
    echo "Если домен только что направили на этот сервер — подождите несколько"
    echo "минут, пока Caddy получит сертификат Let's Encrypt."

    # tgbot.service уже мог успеть запуститься со старым WEBAPP_URL (пустым) —
    # перезапускаем, чтобы кнопка приложения в Telegram подхватила новый адрес.
    systemctl restart tgbot
elif [ -n "$WEBAPP_VIA_TUNNEL" ]; then
    echo "WEBAPP_DOMAIN не задан, но включён WEBAPP_VIA_CLOUDFLARE_TUNNEL —"
    echo "поднимаю Mini App без домена через Cloudflare Tunnel..."
    bash "$PROJECT_DIR/setup_cloudflare_tunnel.sh" || true
else
    echo "WEBAPP_DOMAIN и WEBAPP_VIA_CLOUDFLARE_TUNNEL не заданы в .env —"
    echo "пропускаю настройку мини-приложения. Варианты (см. README,"
    echo "раздел «Mini App»): свой домен — впишите WEBAPP_DOMAIN=ваш.домен,"
    echo "или без домена бесплатно — впишите WEBAPP_VIA_CLOUDFLARE_TUNNEL=1."
    echo "Затем запустите sudo bash deploy.sh ещё раз."
fi

echo "=== Статус ==="
sleep 2
systemctl status tgbot --no-pager || true
if [ -n "$WEBAPP_DOMAIN" ] || [ -n "$WEBAPP_VIA_TUNNEL" ]; then
    systemctl status tgbot-webapp --no-pager || true
fi
if [ -n "$WEBAPP_VIA_TUNNEL" ] && [ -z "$WEBAPP_DOMAIN" ]; then
    systemctl status cloudflared-tunnel --no-pager || true
fi

echo
echo "Готово. Логи бота: journalctl -u tgbot -f"
if [ -n "$WEBAPP_DOMAIN" ] || [ -n "$WEBAPP_VIA_TUNNEL" ]; then
    echo "Логи Mini App: journalctl -u tgbot-webapp -f"
fi
if [ -n "$WEBAPP_VIA_TUNNEL" ] && [ -z "$WEBAPP_DOMAIN" ]; then
    echo "Логи туннеля: journalctl -u cloudflared-tunnel -f"
fi
echo "Дальше в Telegram: /start, затем /whoami -> впишите chat_id в .env как"
echo "ADMIN_CHAT_IDS и перезапустите: systemctl restart tgbot"
