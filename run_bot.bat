@echo off
rem Запускает бота из папки, где лежит этот файл, и перезапускает его,
rem если он упадёт (например, из-за временной ошибки сети).
setlocal
cd /d %~dp0
call .venv\Scripts\activate.bat

:loop
python -m bot.main
echo.
echo [%date% %time%] Бот остановился. Перезапуск через 10 секунд...
echo Чтобы остановить бота насовсем — закройте это окно.
timeout /t 10 /nobreak >nul
goto loop
