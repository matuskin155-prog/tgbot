const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();
if (tg.setHeaderColor) {
  try { tg.setHeaderColor("secondary_bg_color"); } catch (e) { /* старые клиенты */ }
}

const INIT_DATA = tg.initData || "";
const content = document.getElementById("content");
const titleEl = document.getElementById("page-title");
const subtitleEl = document.getElementById("page-subtitle");
let STATE = null;

function escapeHtml(str) {
  // Используется и для текста, и для значений внутри HTML-атрибутов
  // (например data-id="...") - innerHTML сам по себе не экранирует
  // кавычки (они не нужны для текстовых узлов), поэтому добавляем это вручную.
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function skeleton(n) {
  return '<div class="skeleton-list">' + '<div class="skeleton-card"></div>'.repeat(n) + "</div>";
}

function setSubtitle(text) {
  subtitleEl.textContent = text;
}

const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

function dateHeading(isoDate) {
  const today = new Date();
  const todayIso = today.toLocaleDateString("en-CA"); // YYYY-MM-DD, локальная дата
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const tomorrowIso = tomorrow.toLocaleDateString("en-CA");

  if (isoDate === todayIso) return "Сегодня";
  if (isoDate === tomorrowIso) return "Завтра";

  const d = new Date(isoDate + "T00:00:00");
  return `${WEEKDAYS[d.getDay()].replace(/^./, (c) => c.toUpperCase())}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

function eventCard(e, { tappable = false } = {}) {
  const liveClass = e.is_ongoing ? "is-live" : "";
  const liveBadge = e.is_ongoing ? '<span class="live-badge"><span class="live-dot"></span>сейчас</span>' : "";
  return `
    <div class="card ${liveClass} ${tappable ? "tappable" : ""}" ${tappable ? `data-id="${escapeHtml(e.id)}"` : ""}>
      <div class="row-top">
        <span class="time">${escapeHtml(e.when)}</span>
        ${liveBadge}
      </div>
      <div class="title">${escapeHtml(e.summary)}</div>
      ${e.location ? `<div class="loc">📍 ${escapeHtml(e.location)}</div>` : ""}
    </div>
  `;
}

function emptyState(emoji, text) {
  return `<div class="empty"><span class="emoji">${emoji}</span>${text}</div>`;
}

function renderEventList(events, { emptyEmoji = "🎉", emptyText = "Событий нет", tappable = false } = {}) {
  if (!events.length) return emptyState(emptyEmoji, emptyText);
  return events.map((e) => eventCard(e, { tappable })).join("");
}

function renderGroupedByDate(events) {
  if (!events.length) return emptyState("🎉", "Событий нет");
  let html = "";
  let lastDate = null;
  for (const e of events) {
    if (e.date !== lastDate) {
      html += `<div class="date-heading">${dateHeading(e.date)}</div>`;
      lastDate = e.date;
    }
    html += eventCard(e);
  }
  return html;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": INIT_DATA,
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let text = await res.text();
    try { text = JSON.parse(text).errors ? JSON.stringify(JSON.parse(text).errors) : text; } catch (e) { /* не json */ }
    throw new Error(text || ("Ошибка " + res.status));
  }
  return res.json();
}

async function loadState() {
  STATE = await api("/api/state");
}

async function showToday() {
  titleEl.textContent = "Сегодня";
  setSubtitle("");
  const subBtn = STATE.is_subscribed
    ? '<button class="btn secondary" id="sub-toggle">🔕 Отписаться от напоминаний</button>'
    : '<button class="btn" id="sub-toggle">🔔 Подписаться на напоминания</button>';
  content.innerHTML = subBtn + skeleton(2);
  try {
    const events = await api("/api/events/today");
    setSubtitle(events.length ? `${events.length} ${pluralEvents(events.length)}` : "Свободный день");
    content.innerHTML = subBtn + renderEventList(events, { emptyEmoji: "🎉", emptyText: "Событий на сегодня нет" });
  } catch (e) {
    content.innerHTML = subBtn + emptyState("⚠️", "Не удалось загрузить: " + escapeHtml(e.message));
  }
  document.getElementById("sub-toggle").onclick = async () => {
    await api(STATE.is_subscribed ? "/api/unsubscribe" : "/api/subscribe", { method: "POST" });
    await loadState();
    showToday();
  };
}

function pluralEvents(n) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return "событий";
  if (mod10 === 1) return "событие";
  if (mod10 >= 2 && mod10 <= 4) return "события";
  return "событий";
}

async function showUpcoming() {
  titleEl.textContent = "Ближайшие события";
  setSubtitle("");
  content.innerHTML = skeleton(3);
  try {
    const events = await api("/api/events/upcoming");
    setSubtitle(events.length ? `${events.length} ${pluralEvents(events.length)}` : "");
    content.innerHTML = renderGroupedByDate(events);
  } catch (e) {
    content.innerHTML = emptyState("⚠️", "Не удалось загрузить: " + escapeHtml(e.message));
  }
}

async function showOlympiads() {
  titleEl.textContent = "Олимпиады";
  setSubtitle("");
  let html = STATE.is_admin
    ? '<button class="btn secondary" id="check-olympiads">🔍 Проверить сейчас</button>'
    : "";
  content.innerHTML = html + skeleton(4);
  try {
    const items = await api("/api/olympiads");
    const changedCount = items.filter((o) => o.changed).length;
    setSubtitle(`${items.length} отслеживается` + (changedCount ? ` · ${changedCount} обновилось` : ""));
    html += items.map((o) => `
      <div class="card">
        <a href="${o.url}" target="_blank" rel="noopener">
          <div class="title">${escapeHtml(o.name)}${o.changed ? '<span class="badge new">● обновилось</span>' : ""}</div>
          <div class="olympiad-link">🔗 ${escapeHtml(new URL(o.url).hostname)}</div>
        </a>
      </div>
    `).join("");
  } catch (e) {
    html += emptyState("⚠️", "Ошибка: " + escapeHtml(e.message));
  }
  content.innerHTML = html;
  if (STATE.is_admin) {
    document.getElementById("check-olympiads").onclick = async (ev) => {
      ev.target.textContent = "Проверяю… (до минуты)";
      ev.target.disabled = true;
      try {
        const res = await api("/api/olympiads/check", { method: "POST" });
        const parts = [];
        if (res.added_events.length) {
          parts.push("В календарь добавлено/обновлено: " + res.added_events.map((e) => `${e.name}${e.label ? " — " + e.label : ""} (${e.start_date})`).join(", "));
        }
        if (res.changed.length) {
          parts.push("Изменились страницы: " + res.changed.map((c) => c.name).join(", "));
        }
        tg.showAlert(parts.length ? parts.join("\n") : "Изменений не найдено");
      } catch (e) {
        tg.showAlert("Ошибка: " + e.message);
      }
      showOlympiads();
    };
  }
}

async function showSettings() {
  titleEl.textContent = "Настройки";
  setSubtitle(STATE.is_admin ? "Администратор" : "");
  if (!STATE.is_admin) {
    content.innerHTML = `
      <div class="info-card">
        <div class="title">Ваш chat_id: ${STATE.chat_id}</div>
        <div class="loc">Напоминания: ${STATE.is_subscribed ? "включены 🔔" : "выключены 🔕"}</div>
      </div>
      ${emptyState("🔒", "Настройки бота доступны только администратору.")}
    `;
    return;
  }

  const cfg = STATE.config;
  content.innerHTML = `
    <div class="section-title">Календарь</div>
    <div class="field"><label>ID календаря Google</label><input id="f-calendar" value="${escapeHtml(cfg.calendar_id)}" /></div>

    <div class="section-title">Напоминания</div>
    <div class="field">
      <label>За сколько минут напоминать</label>
      <input id="f-reminders" value="${escapeHtml(cfg.reminder_minutes_before)}" />
      <div class="hint">Через запятую, например: 60, 10</div>
    </div>
    <div class="field"><label>Горизонт просмотра, часы</label><input id="f-lookahead" value="${cfg.lookahead_hours}" /></div>
    <div class="field"><label>Время ежедневной сводки, ЧЧ:ММ</label><input id="f-digest" value="${escapeHtml(cfg.daily_digest_time)}" /></div>
    <div class="field"><label>Часовой пояс</label><input id="f-timezone" value="${escapeHtml(cfg.timezone)}" /></div>

    <div class="section-title">Автоматика</div>
    <div class="field">
      <label>Интервал опроса календаря, сек</label>
      <input id="f-interval" value="${cfg.poll_interval_seconds}" />
      <div class="hint">Как часто бот проверяет календарь на новые события</div>
    </div>

    <button class="btn" id="save-settings">💾 Сохранить</button>
    <button class="btn danger" id="open-delete">🗑 Удалить событие из календаря</button>
  `;

  document.getElementById("save-settings").onclick = async () => {
    const btn = document.getElementById("save-settings");
    btn.disabled = true;
    try {
      await api("/api/config", {
        method: "POST",
        body: JSON.stringify({
          calendar_id: document.getElementById("f-calendar").value,
          reminder_minutes_before: document.getElementById("f-reminders").value,
          lookahead_hours: document.getElementById("f-lookahead").value,
          poll_interval_seconds: document.getElementById("f-interval").value,
          timezone: document.getElementById("f-timezone").value,
          daily_digest_time: document.getElementById("f-digest").value,
        }),
      });
      await loadState();
      tg.showAlert("Сохранено! Интервал опроса и время сводки применятся в течение ~30 секунд.");
      showSettings();
    } catch (e) {
      tg.showAlert("Не сохранено: " + e.message);
      btn.disabled = false;
    }
  };

  document.getElementById("open-delete").onclick = showDeletePicker;
}

async function showDeletePicker() {
  titleEl.textContent = "Удалить событие";
  setSubtitle("Ближайшие 30 дней");
  content.innerHTML = skeleton(3);
  let events;
  try {
    events = await api("/api/events/deletable");
  } catch (e) {
    content.innerHTML = emptyState("⚠️", "Ошибка: " + escapeHtml(e.message)) + backButton();
    bindBack();
    return;
  }

  if (!events.length) {
    content.innerHTML = emptyState("📭", "Событий в ближайшие 30 дней нет") + backButton();
  } else {
    content.innerHTML = renderEventList(events, { tappable: true }) + backButton();
    content.querySelectorAll(".card.tappable").forEach((card) => {
      card.onclick = () => confirmDelete(card.dataset.id, card.querySelector(".title").textContent);
    });
  }
  bindBack();
}

function backButton() {
  return '<button class="btn secondary small" id="back-btn" style="margin-top:6px;">← Назад к настройкам</button>';
}
function bindBack() {
  document.getElementById("back-btn").onclick = showSettings;
}

function confirmDelete(eventId, summary) {
  tg.showConfirm(`Удалить «${summary}» из календаря? Это затронет всех подписчиков.`, async (confirmed) => {
    if (!confirmed) return;
    try {
      await api("/api/events/delete", { method: "POST", body: JSON.stringify({ event_id: eventId }) });
      tg.showAlert("Событие удалено");
    } catch (e) {
      tg.showAlert("Ошибка: " + e.message);
    }
    showDeletePicker();
  });
}

const TABS = { today: showToday, upcoming: showUpcoming, olympiads: showOlympiads, settings: showSettings };

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    TABS[btn.dataset.tab]();
  };
});

(async () => {
  try {
    await loadState();
  } catch (e) {
    content.innerHTML = emptyState(
      "🔒",
      `Не удалось авторизоваться: ${escapeHtml(e.message)}<br><br>Открывайте приложение через кнопку в чате бота, а не напрямую в браузере.`
    );
    return;
  }
  showToday();
})();
