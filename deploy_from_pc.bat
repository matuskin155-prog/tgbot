@echo off
setlocal enabledelayedexpansion

rem ============================================================
rem  Разворачивает/обновляет бота на сервере одним запуском —
rem  с ВАШЕГО компьютера, без ручного захода по SSH.
rem
rem  Что делает:
rem   1) по SSH клонирует код на сервере (или обновляет, если
rem      уже клонирован);
rem   2) при первом запуске загружает .env и service_account.json
rem      с этого компьютера на сервер (если на сервере их ещё нет —
rem      если уже есть, не трогает, чтобы не затереть то, что вы
rem      правили прямо на сервере, например ADMIN_CHAT_IDS);
rem   3) запускает deploy.sh на сервере (ставит зависимости,
rem      поднимает systemd-автозапуск).
rem
rem  IP сервера спросит один раз и запомнит в server.ini —
rem  этот файл не попадёт в GitHub (см. .gitignore).
rem
rem  Нужен ssh/scp — они есть по умолчанию в Windows 10/11.
rem  Чтобы не вводить пароль на каждом шаге, один раз настройте
rem  вход по ключу (см. README.md, раздел про deploy_from_pc.bat).
rem ============================================================

set SERVER_USER=root
set REPO_URL=https://github.com/matuskin155-prog/tgbot.git
set BRANCH=claude/telegram-google-calendar-reminders-nna72g
set REMOTE_DIR=tgbot

if exist server.ini (
    for /f "tokens=1,2 delims==" %%A in (server.ini) do (
        if "%%A"=="SERVER_IP" set SERVER_IP=%%B
    )
)

if not defined SERVER_IP (
    set /p SERVER_IP="IP сервера: "
    echo SERVER_IP=%SERVER_IP%> server.ini
)

echo.
echo === Подключаюсь к %SERVER_IP%, клонирую/обновляю код ===
ssh %SERVER_USER%@%SERVER_IP% "mkdir -p ~/%REMOTE_DIR% && cd ~/%REMOTE_DIR% && (git rev-parse --git-dir >/dev/null 2>&1 && git pull || git clone -b %BRANCH% %REPO_URL% .)"
if errorlevel 1 (
    echo.
    echo Не получилось подключиться или обновить код. Проверьте IP и доступ по SSH.
    pause
    exit /b 1
)

echo.
echo === Проверяю .env на сервере ===
ssh %SERVER_USER%@%SERVER_IP% "test -f ~/%REMOTE_DIR%/.env"
if errorlevel 1 (
    if exist .env (
        echo .env на сервере не найден — загружаю локальный .env
        scp .env %SERVER_USER%@%SERVER_IP%:~/%REMOTE_DIR%/.env
    ) else (
        echo На сервере нет .env, и локального .env рядом с этим bat-файлом тоже нет.
        echo Скопируйте .env.example в .env, заполните TELEGRAM_BOT_TOKEN и запустите снова.
    )
) else (
    echo .env на сервере уже есть — не трогаю его.
)

echo.
echo === Проверяю service_account.json на сервере ===
ssh %SERVER_USER%@%SERVER_IP% "test -f ~/%REMOTE_DIR%/service_account.json"
if errorlevel 1 (
    if exist service_account.json (
        echo service_account.json на сервере не найден — загружаю локальный файл
        scp service_account.json %SERVER_USER%@%SERVER_IP%:~/%REMOTE_DIR%/service_account.json
    ) else (
        echo На сервере нет service_account.json, и локального рядом тоже нет.
        echo Положите его рядом с этим bat-файлом и запустите снова.
    )
) else (
    echo service_account.json на сервере уже есть — не трогаю его.
)

echo.
echo === Запускаю deploy.sh на сервере ===
ssh %SERVER_USER%@%SERVER_IP% "cd ~/%REMOTE_DIR% && sudo bash deploy.sh"

echo.
echo Готово. Посмотреть логи: ssh %SERVER_USER%@%SERVER_IP% "journalctl -u tgbot -f"
pause
