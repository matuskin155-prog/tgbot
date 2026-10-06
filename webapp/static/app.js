const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();
if (tg.setHeaderColor) {
  try { tg.setHeaderColor("secondary_bg_color"); } catch (e) { /* старые клиенты */ }
}

const INIT_DATA = tg.initData || "";
const content = document.getElementById("content");
const titleEl = document.getElementById("page-title");
let STATE = null;

function escapeHtml(str) {
  // Используется и для текста, и для значений внутри HTML-атрибутов
  // (например data-id="...") - innerHTML сам по себе не экранирует
  // кавычки (они не нужны для текстовых узлов), поэтому добавляем это вручную.
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
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

function renderEventList(events) {
  if (!events.length) return '<div class="empty">Событий нет 🎉</div>';
  return events.map((e) => `
    <div class="card">
      <div class="time">${escapeHtml(e.when)}</div>
      <div class="title">${escapeHtml(e.summary)}</div>
      ${e.location ? `<div class="loc">📍 ${escapeHtml(e.location)}</div>` : ""}
    </div>
  `).join("");
}

async function loadState() {
  STATE = await api("/api/state");
}

async function showToday() {
  titleEl.textContent = "Сегодня";
  const subBtn = STATE.is_subscribed
    ? '<button class="btn secondary" id="sub-toggle">🔕 Отписаться от напоминаний</button>'
    : '<button class="btn" id="sub-toggle">🔔 Подписаться на напоминания</button>';
  content.innerHTML = subBtn + '<div class="empty">Загрузка…</div>';
  try {
    const events = await api("/api/events/today");
    content.innerHTML = subBtn + renderEventList(events);
  } catch (e) {
    content.innerHTML = subBtn + `<div class="empty">Не удалось загрузить: ${escapeHtml(e.message)}</div>`;
  }
  document.getElementById("sub-toggle").onclick = async () => {
    await api(STATE.is_subscribed ? "/api/unsubscribe" : "/api/subscribe", { method: "POST" });
    await loadState();
    showToday();
  };
}

async function showUpcoming() {
  titleEl.textContent = "Ближайшие события";
  content.innerHTML = '<div class="empty">Загрузка…</div>';
  try {
    const events = await api("/api/events/upcoming");
    content.innerHTML = renderEventList(events);
  } catch (e) {
    content.innerHTML = `<div class="empty">Не удалось загрузить: ${escapeHtml(e.message)}</div>`;
  }
}

async function showOlympiads() {
  titleEl.textContent = "Олимпиады";
  let html = STATE.is_admin
    ? '<button class="btn secondary" id="check-olympiads">🔍 Проверить сейчас</button>'
    : "";
  content.innerHTML = html + '<div class="empty">Загрузка…</div>';
  try {
    const items = await api("/api/olympiads");
    html += items.map((o) => `
      <div class="card">
        <a href="${o.url}" target="_blank" rel="noopener">
          <div class="title">${escapeHtml(o.name)}${o.changed ? '<span class="badge-dot">●</span>' : ""}</div>
        </a>
      </div>
    `).join("");
  } catch (e) {
    html += `<div class="empty">Ошибка: ${escapeHtml(e.message)}</div>`;
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
          parts.push("В календарь добавлено/обновлено: " + res.added_events.map((e) => `${e.name} (${e.start_date})`).join(", "));
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
  if (!STATE.is_admin) {
    content.innerHTML = `
      <div class="card">
        <div class="title">chat_id: ${STATE.chat_id}</div>
        <div class="loc">Подписка: ${STATE.is_subscribed ? "включена" : "выключена"}</div>
      </div>
      <div class="empty">Настройки бота доступны только администратору.</div>
    `;
    return;
  }

  const cfg = STATE.config;
  content.innerHTML = `
    <div class="field"><label>Календарь (ID)</label><input id="f-calendar" value="${escapeHtml(cfg.calendar_id)}" /></div>
    <div class="field"><label>Напоминания за, мин (через запятую)</label><input id="f-reminders" value="${escapeHtml(cfg.reminder_minutes_before)}" /></div>
    <div class="field"><label>Горизонт просмотра, часы</label><input id="f-lookahead" value="${cfg.lookahead_hours}" /></div>
    <div class="field"><label>Интервал опроса, сек</label><input id="f-interval" value="${cfg.poll_interval_seconds}" /></div>
    <div class="field"><label>Часовой пояс</label><input id="f-timezone" value="${escapeHtml(cfg.timezone)}" /></div>
    <div class="field"><label>Время ежедневной сводки, ЧЧ:ММ</label><input id="f-digest" value="${escapeHtml(cfg.daily_digest_time)}" /></div>
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
  content.innerHTML = '<div class="empty">Загрузка…</div>';
  let events;
  try {
    events = await api("/api/events/deletable");
  } catch (e) {
    content.innerHTML = `<div class="empty">Ошибка: ${escapeHtml(e.message)}</div>` + backButton();
    bindBack();
    return;
  }

  if (!events.length) {
    content.innerHTML = '<div class="empty">Событий в ближайшие 30 дней нет</div>' + backButton();
  } else {
    content.innerHTML = events.map((e) => `
      <div class="card" data-id="${escapeHtml(e.id)}" style="cursor:pointer;">
        <div class="time">${escapeHtml(e.when)}</div>
        <div class="title">${escapeHtml(e.summary)}</div>
      </div>
    `).join("") + backButton();
    content.querySelectorAll(".card").forEach((card) => {
      card.onclick = () => confirmDelete(card.dataset.id, card.querySelector(".title").textContent);
    });
  }
  bindBack();
}

function backButton() {
  return '<button class="btn secondary" id="back-btn">← Назад к настройкам</button>';
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
    content.innerHTML = `<div class="empty">Не удалось авторизоваться: ${escapeHtml(e.message)}<br><br>Открывайте приложение через кнопку в чате бота, а не напрямую в браузере.</div>`;
    return;
  }
  showToday();
})();
