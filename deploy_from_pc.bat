@echo off
setlocal enabledelayedexpansion

rem ============================================================
rem  Deploys/updates the bot on your server from this computer,
rem  without manually opening an SSH console.
rem
rem  What it does:
rem   1) clones the code on the server over SSH (or pulls, if
rem      already cloned);
rem   2) on first run, uploads .env and service_account.json from
rem      this computer to the server (only if the server doesn't
rem      already have them, so edits made directly on the server,
rem      e.g. ADMIN_CHAT_IDS, are never overwritten);
rem   3) runs deploy.sh on the server (installs dependencies,
rem      sets up the systemd autostart service).
rem
rem  The server IP is asked once and cached in server.ini, which
rem  never reaches GitHub (see .gitignore).
rem
rem  Requires ssh/scp - both ship with Windows 10/11 by default.
rem  To avoid typing your password at every step, set up SSH key
rem  login once (see README.md, the deploy_from_pc.bat section).
rem
rem  NOTE: this file is kept pure ASCII on purpose. Cyrillic text
rem  inside a .bat file can break cmd.exe's parser depending on
rem  the active code page, causing commands like git/ssh to fail
rem  with "is not recognized" even though they are installed.
rem  All explanations in Russian live in README.md instead.
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
    set /p SERVER_IP="Server IP: "
    echo SERVER_IP=%SERVER_IP%> server.ini
)

echo.
echo === Connecting to %SERVER_IP%, cloning/updating code ===
ssh %SERVER_USER%@%SERVER_IP% "mkdir -p ~/%REMOTE_DIR% && cd ~/%REMOTE_DIR% && (git rev-parse --git-dir >/dev/null 2>&1 && git pull || git clone -b %BRANCH% %REPO_URL% .)"
if errorlevel 1 (
    echo.
    echo Could not connect or update the code. Check the IP and SSH access.
    pause
    exit /b 1
)

echo.
echo === Checking .env on the server ===
ssh %SERVER_USER%@%SERVER_IP% "test -f ~/%REMOTE_DIR%/.env"
if errorlevel 1 (
    if exist .env (
        echo .env not found on server - uploading local .env
        scp .env %SERVER_USER%@%SERVER_IP%:~/%REMOTE_DIR%/.env
    ) else (
        echo No .env on the server, and no local .env next to this bat file either.
        echo Copy .env.example to .env, fill in TELEGRAM_BOT_TOKEN, then run this again.
    )
) else (
    echo .env already exists on the server - leaving it alone.
)

echo.
echo === Checking service_account.json on the server ===
ssh %SERVER_USER%@%SERVER_IP% "test -f ~/%REMOTE_DIR%/service_account.json"
if errorlevel 1 (
    if exist service_account.json (
        echo service_account.json not found on server - uploading local file
        scp service_account.json %SERVER_USER%@%SERVER_IP%:~/%REMOTE_DIR%/service_account.json
    ) else (
        echo No service_account.json on the server, and no local copy here either.
        echo Put it next to this bat file and run this again.
    )
) else (
    echo service_account.json already exists on the server - leaving it alone.
)

echo.
echo === Running deploy.sh on the server ===
ssh %SERVER_USER%@%SERVER_IP% "cd ~/%REMOTE_DIR% && sudo bash deploy.sh"

echo.
echo Done. View logs with: ssh %SERVER_USER%@%SERVER_IP% "journalctl -u tgbot -f"
pause
