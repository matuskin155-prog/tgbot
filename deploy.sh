#!/usr/bin/env bash
# Разворачивает бота на Debian/Ubuntu-сервере одной командой:
# системные пакеты -> venv -> зависимости -> systemd-автозапуск.
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

echo "=== 1/4: системные пакеты (python3, venv, Google Chrome) ==="
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

echo "=== 2/4: виртуальное окружение и зависимости ==="
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

echo "=== 3/4: systemd-автозапуск ==="
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

echo "=== 4/4: статус ==="
sleep 2
systemctl status tgbot --no-pager || true

echo
echo "Готово. Логи: journalctl -u tgbot -f"
echo "Дальше в Telegram: /start, затем /whoami -> впишите chat_id в .env как"
echo "ADMIN_CHAT_IDS и перезапустите: systemctl restart tgbot"
