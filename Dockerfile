FROM python:3.12-slim

WORKDIR /app

# chromium + chromium-driver — для слежения за страницами олимпиад через
# headless-браузер (bot/olympiad_watch.py). Контейнер не видит браузер,
# который может быть установлен на хосте, поэтому ставим свой.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

ENV BROWSER_EXECUTABLE_PATH=/usr/bin/chromium

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

CMD ["python", "-m", "bot.main"]
