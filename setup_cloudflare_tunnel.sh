#!/usr/bin/env bash
set -uo pipefail
# Не -e: это сервисный скрипт, который должен продолжать работать, даже
# если одна команда временно не сработала (его перезапустит systemd).

# Поднимает Telegram Mini App БЕЗ собственного домена — через бесплатный
# Cloudflare Tunnel (режим "quick tunnel"): доступ по случайному адресу
# вида https://случайные-слова.trycloudflare.com с готовым HTTPS от
# Cloudflare, без регистрации и без домена.
#
# ВАЖНО (это ограничение самой Cloudflare, не моя прихоть): quick tunnel
# предназначен для разработки/временного использования — адрес МЕНЯЕТСЯ
# при каждом перезапуске туннеля (перезагрузка сервера, падение процесса
# и т.п.). Служба ниже сама подхватывает новый адрес и обновляет кнопку
# приложения у бота, но несколько секунд после смены адреса кнопка может
# ссылаться на уже неработающий старый. Надёжнее — свой домен
# (WEBAPP_DOMAIN в .env, см. README), это просто бесплатная альтернатива,
# когда домена нет и заводить не хочется.
#
# Запускать на сервере, от root, из папки проекта:
#   sudo bash setup_cloudflare_tunnel.sh

if [[ "${EUID}" -ne 0 ]]; then
    echo "Запустите этот скрипт от root: sudo bash setup_cloudflare_tunnel.sh" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Порт настраиваемый - на случай, если 8787 занят другим вашим проектом на
# этом же сервере (впишите WEBAPP_PORT=другой-порт в .env и перезапустите).
WEBAPP_PORT="$(grep -E '^WEBAPP_PORT=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
WEBAPP_PORT="${WEBAPP_PORT:-8787}"

echo "==> Устанавливаю cloudflared..."
if ! command -v cloudflared >/dev/null 2>&1; then
    TMP_DEB="$(mktemp --suffix=.deb)"
    if curl -fsSL -o "$TMP_DEB" \
        https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb; then
        apt-get install -y "$TMP_DEB"
    else
        echo "Не удалось скачать cloudflared с GitHub." >&2
        rm -f "$TMP_DEB"
        exit 1
    fi
    rm -f "$TMP_DEB"
else
    echo "    cloudflared уже установлен."
fi

echo "==> Настраиваю службу веб-приложения (tgbot-webapp)..."
cat > /etc/systemd/system/tgbot-webapp.service <<EOF
[Unit]
Description=Telegram bot Mini App web server
After=network.target

[Service]
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/.venv/bin/python -m webapp.server
EnvironmentFile=$SCRIPT_DIR/.env
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable tgbot-webapp
systemctl restart tgbot-webapp

echo "==> Устанавливаю скрипт-наблюдатель за адресом туннеля..."
cat > "$SCRIPT_DIR/cloudflared_tunnel_watch.sh" <<'WATCHER'
#!/usr/bin/env bash
# Запускает cloudflared quick tunnel; как только Cloudflare выдаёт новый
# адрес (https://...trycloudflare.com), переписывает WEBAPP_URL в .env и
# перезапускает tgbot, чтобы кнопка приложения обновилась.
#
# Сгенерирован setup_cloudflare_tunnel.sh — руками не редактировать,
# перезапишется при повторном запуске того скрипта.
set -uo pipefail
cd "$(dirname "$0")"
ENV_FILE="$(pwd)/.env"
WEBAPP_PORT="$(grep -E '^WEBAPP_PORT=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
WEBAPP_PORT="${WEBAPP_PORT:-8787}"

update_webapp_url() {
    local new_url="$1"
    local current
    current="$(grep -E '^WEBAPP_URL=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
    if [[ "$new_url" == "$current" ]]; then
        return
    fi
    if grep -q '^WEBAPP_URL=' "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^WEBAPP_URL=.*|WEBAPP_URL=$new_url|" "$ENV_FILE"
    else
        echo "WEBAPP_URL=$new_url" >> "$ENV_FILE"
    fi
    echo "Новый адрес Mini App: $new_url - перезапускаю tgbot"
    systemctl restart tgbot.service
}

cloudflared tunnel --url "http://127.0.0.1:${WEBAPP_PORT}" --no-autoupdate 2>&1 | while IFS= read -r line; do
    echo "$line"
    if [[ "$line" =~ (https://[A-Za-z0-9-]+\.trycloudflare\.com) ]]; then
        update_webapp_url "${BASH_REMATCH[1]}"
    fi
done
WATCHER
chmod +x "$SCRIPT_DIR/cloudflared_tunnel_watch.sh"

echo "==> Настраиваю службу туннеля (cloudflared-tunnel)..."
cat > /etc/systemd/system/cloudflared-tunnel.service <<EOF
[Unit]
Description=Cloudflare quick tunnel for the bot Mini App
After=network.target tgbot-webapp.service

[Service]
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/cloudflared_tunnel_watch.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable cloudflared-tunnel
systemctl restart cloudflared-tunnel

echo "==> Жду, пока Cloudflare выдаст адрес (обычно 5-15 секунд)..."
CURRENT_URL=""
for _ in $(seq 1 30); do
    sleep 1
    CURRENT_URL="$(grep -E '^WEBAPP_URL=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
    if [[ -n "$CURRENT_URL" ]]; then
        break
    fi
done

if [[ -n "$CURRENT_URL" ]]; then
    echo
    echo "Mini App доступен: $CURRENT_URL"
    echo "Бот уже перезапущен с этим адресом - проверьте кнопку в Telegram (/start)."
else
    echo
    echo "Адрес пока не появился - смотрите логи: journalctl -u cloudflared-tunnel -f" >&2
fi

echo
echo "ВАЖНО: это бесплатный временный адрес от Cloudflare - он меняется"
echo "при каждом перезапуске туннеля (например, после перезагрузки сервера)."
echo "Служба cloudflared-tunnel сама обновит кнопку бота при смене адреса -"
echo "никаких действий от вас не требуется, просто дайте ей секунд 10-20"
echo "после перезагрузки сервера. Надёжнее - свой домен (WEBAPP_DOMAIN в .env)."
