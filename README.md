# tgbot — напоминания из Google Calendar в Telegram

Telegram-бот, который периодически опрашивает Google Calendar и присылает
напоминания о предстоящих событиях в подписанные чаты (за N минут до начала,
настраивается).

## Как это работает

- Бот подключается к Google Calendar через **сервис-аккаунт** (без ручного
  OAuth-логина на сервере) и читает один календарь, указанный в конфиге.
- Каждые `POLL_INTERVAL_SECONDS` секунд бот запрашивает события на ближайшие
  `LOOKAHEAD_HOURS` часов и для каждого события проверяет пороги
  `REMINDER_MINUTES_BEFORE` (например, 60 и 10 минут до начала).
- Каждое напоминание отправляется один раз на чат — это отслеживается в
  локальной SQLite-базе (`DATABASE_PATH`), поэтому дубликатов не будет даже
  при частом опросе или перезапуске бота.
- Подписаться/отписаться от напоминаний может любой чат командами
  `/subscribe` и `/unsubscribe`.

## 1. Создать Telegram-бота

1. Напишите [@BotFather](https://t.me/BotFather) в Telegram, отправьте
   `/newbot` и следуйте инструкциям.
2. Скопируйте выданный токен — это `TELEGRAM_BOT_TOKEN`.

## 2. Настроить доступ к Google Calendar

1. Откройте [Google Cloud Console](https://console.cloud.google.com/) и
   создайте (или выберите) проект.
2. Включите **Google Calendar API**: APIs & Services → Library → Google
   Calendar API → Enable.
3. Создайте сервис-аккаунт: APIs & Services → Credentials → Create
   Credentials → Service account.
4. У созданного сервис-аккаунта откройте вкладку **Keys** → Add Key →
   Create new key → JSON. Скачается файл ключа — сохраните его в проекте как
   `service_account.json` (или укажите свой путь в
   `GOOGLE_SERVICE_ACCOUNT_FILE`). **Не коммитьте этот файл** — он уже
   добавлен в `.gitignore`.
5. Скопируйте email сервис-аккаунта (вида
   `xxxx@xxxx.iam.gserviceaccount.com`).
6. В Google Calendar откройте настройки нужного календаря → **Share with
   specific people** → добавьте email сервис-аккаунта с правом «See all
   event details» (достаточно для чтения).
7. Возьмите **Calendar ID** в настройках календаря (раздел «Integrate
   calendar») — это либо `primary` для основного календаря аккаунта-владельца,
   либо адрес вида `xxxxx@group.calendar.google.com` для отдельного
   календаря.

## 3. Настроить и запустить бота

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# отредактируйте .env: TELEGRAM_BOT_TOKEN, GOOGLE_CALENDAR_ID, TIMEZONE и т.д.
# положите service_account.json рядом (или укажите путь в .env)

python -m bot.main
```

После запуска напишите боту в Telegram `/start`, затем `/subscribe` в каждом
чате, куда нужно слать напоминания.

## Команды бота

| Команда        | Действие                                             |
|-----------------|-------------------------------------------------------|
| `/start`        | Приветствие и список команд                          |
| `/help`         | То же самое                                           |
| `/subscribe`    | Включить напоминания в этом чате                     |
| `/unsubscribe`  | Выключить напоминания в этом чате                     |
| `/today`        | Показать события на ближайшие 24 часа                |
| `/upcoming`     | Показать все события в пределах `LOOKAHEAD_HOURS`    |
| `/status`       | Текущие настройки и статус подписки                  |

## Конфигурация (`.env`)

| Переменная                  | Описание                                               | По умолчанию         |
|------------------------------|----------------------------------------------------------|------------------------|
| `TELEGRAM_BOT_TOKEN`         | Токен бота от @BotFather                                  | — (обязательно)       |
| `GOOGLE_CALENDAR_ID`         | ID календаря Google                                        | `primary`              |
| `GOOGLE_SERVICE_ACCOUNT_FILE`| Путь к JSON-ключу сервис-аккаунта                         | `service_account.json` |
| `REMINDER_MINUTES_BEFORE`    | За сколько минут до события напоминать (список через `,`) | `60,10`                |
| `POLL_INTERVAL_SECONDS`      | Как часто опрашивать календарь, сек.                       | `60`                   |
| `LOOKAHEAD_HOURS`            | Горизонт просмотра событий, часы                           | `24`                   |
| `TIMEZONE`                   | Часовой пояс для отображения времени (IANA, напр. `Europe/Moscow`) | `UTC`          |
| `DATABASE_PATH`              | Путь к файлу SQLite                                        | `bot_data.sqlite3`     |

## Запуск как systemd-сервиса (пример)

```ini
[Unit]
Description=Telegram Google Calendar reminder bot
After=network.target

[Service]
WorkingDirectory=/opt/tgbot
ExecStart=/opt/tgbot/.venv/bin/python -m bot.main
EnvironmentFile=/opt/tgbot/.env
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Структура проекта

```
bot/
  config.py          # чтение настроек из .env
  database.py         # SQLite: подписчики + отправленные напоминания
  google_calendar.py  # клиент Google Calendar API
  handlers.py          # команды Telegram-бота
  reminders.py          # фоновая задача проверки и рассылки напоминаний
  main.py                # точка входа
requirements.txt
.env.example
```
