const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();
if (tg.setHeaderColor) {
  try { tg.setHeaderColor("secondary_bg_color"); } catch (e) { /* старые клиенты */ }
}

// У приложения свой фирменный кавайный пастельный вид (не берём цвета из
// темы собеседника в Telegram) - только переключаем светлый/тёмный вариант
// вслед за самим Telegram, через data-theme на <html>.
function applyColorScheme() {
  document.documentElement.dataset.theme = tg.colorScheme === "dark" ? "dark" : "light";
}
applyColorScheme();
try { tg.onEvent("themeChanged", applyColorScheme); } catch (e) { /* старые клиенты */ }

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

// Тактильный отклик при касаниях - мелочь, но ощущается как нативное
// приложение, а не веб-страница. Не у всех клиентов Telegram есть
// HapticFeedback, поэтому молча игнорируем отсутствие.
function haptic(style) {
  try { tg.HapticFeedback && tg.HapticFeedback.impactOccurred(style || "light"); } catch (e) { /* нет в этом клиенте */ }
}
function hapticNotify(type) {
  try { tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(type); } catch (e) { /* нет в этом клиенте */ }
}

// Живой обратный отсчёт до начала события - обновляется на месте каждые
// 20 секунд (ниже, setInterval), без повторных запросов к серверу.
function countdownText(startTs) {
  const diffMs = new Date(startTs).getTime() - Date.now();
  if (diffMs <= 0) return null;
  const totalMin = Math.round(diffMs / 60000);
  if (totalMin > 180) return null; // дальше 3 часов не показываем - не актуально
  if (totalMin < 1) return "меньше минуты";
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h > 0) return `через ${h} ч${m ? " " + m + " мин" : ""}`;
  return `через ${m} мин`;
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

// Наглядный блок "Этот месяц": сколько событий осталось до конца месяца,
// сколько из них по олимпиадам, и простая разбивка загруженности по
// неделям - чтобы сразу видеть, насколько насыщенный месяц, не открывая
// отдельно "Ближайшие" (у которых горизонт обычно гораздо короче месяца).
function buildMonthSummary(events) {
  const total = events.length;
  const olympiadCount = events.filter((e) => e.olympiad_url).length;

  const weeks = [0, 0, 0, 0, 0];
  for (const e of events) {
    const day = parseInt(e.date.slice(8, 10), 10);
    weeks[Math.min(4, Math.floor((day - 1) / 7))] += 1;
  }
  const maxWeek = Math.max(1, ...weeks);
  const bars = weeks.map((count) => {
    const pct = count === 0 ? 0 : Math.max(12, Math.round((count / maxWeek) * 100));
    const opacity = count === 0 ? 0.25 : (0.4 + 0.6 * (count / maxWeek)).toFixed(2);
    return `
      <div class="month-bar-col">
        <div class="month-bar-track"><div class="month-bar" style="height:${pct}%; opacity:${opacity}"></div></div>
        <div class="month-bar-count">${count || "–"}</div>
      </div>
    `;
  }).join("");

  return `
    <div class="month-card">
      <div class="month-header">📊 Этот месяц</div>
      <div class="month-stats">
        <div class="month-stat">
          <div class="month-stat-num">${total}</div>
          <div class="month-stat-label">${pluralEvents(total)} осталось</div>
        </div>
        <div class="month-stat olympiad">
          <div class="month-stat-num">${olympiadCount}</div>
          <div class="month-stat-label">из них олимпиад</div>
        </div>
      </div>
      ${total ? `<div class="month-bars">${bars}</div><div class="month-bars-hint">по неделям месяца</div>` : ""}
    </div>
  `;
}

async function fetchMonthSummary() {
  try {
    const events = await api("/api/events/month");
    return buildMonthSummary(events);
  } catch (e) {
    return "";
  }
}

function eventCard(e, { tappable = false, index = 0, showDelete = false, showHide = false } = {}) {
  const liveClass = e.is_ongoing ? "is-live" : "";
  const olympiadClass = e.olympiad_url ? "is-olympiad" : "";
  const liveBadge = e.is_ongoing ? '<span class="live-badge"><span class="live-dot"></span>сейчас</span>' : "";
  const olympiadBadge = e.olympiad_url ? '<span class="olympiad-badge">🏅 олимпиада</span>' : "";
  const countdown = !e.is_ongoing && e.start_ts ? countdownText(e.start_ts) : null;
  const countdownBadge = countdown
    ? `<span class="countdown" data-start-ts="${escapeHtml(e.start_ts)}">${countdown}</span>`
    : "";
  // Эти кнопки не показываем на карточках для удаления - там сама карточка
  // целиком уже кликабельна для другого действия, вложенные кнопки внутри
  // неё только путали бы.
  // Ссылка на официальный сайт олимпиады - отдельная, более заметная кнопка
  // (не просто текстовая ссылка, как "открыть в Google Calendar"), чтобы
  // сразу было видно, куда идти за подробностями/регистрацией.
  const olympiadLink = !tappable && e.olympiad_url
    ? `<button class="olympiad-link-btn" data-link="${escapeHtml(e.olympiad_url)}">🏅 Сайт олимпиады</button>`
    : "";
  const calLink = !tappable && e.html_link
    ? `<button class="cal-link" data-link="${escapeHtml(e.html_link)}">🔗 Google Calendar</button>`
    : "";
  const deleteBtn = !tappable && showDelete
    ? `<button class="delete-btn" data-id="${escapeHtml(e.id)}" data-summary="${escapeHtml(e.summary)}">🗑 Удалить</button>`
    : "";
  // "Скрыть у себя" доступно ЛЮБОМУ подписчику (не только админу) - событие
  // в общем календаре не трогает, просто больше не показывается именно ему.
  const hideBtn = !tappable && showHide
    ? `<button class="hide-btn" data-id="${escapeHtml(e.id)}" data-summary="${escapeHtml(e.summary)}">🙈 Скрыть у себя</button>`
    : "";
  const actionsRow = olympiadLink || calLink || deleteBtn || hideBtn
    ? `<div class="row-actions">${olympiadLink}${calLink}${hideBtn}${deleteBtn}</div>`
    : "";
  return `
    <div class="card ${liveClass} ${olympiadClass} ${tappable ? "tappable" : ""}" style="--i:${index}" ${tappable ? `data-id="${escapeHtml(e.id)}"` : ""}>
      <div class="row-top">
        <span class="time">${escapeHtml(e.when)}</span>
        ${liveBadge}
        ${olympiadBadge}
        ${countdownBadge}
      </div>
      <div class="title">${escapeHtml(e.summary)}</div>
      ${e.location ? `<div class="loc">📍 ${escapeHtml(e.location)}</div>` : ""}
      ${actionsRow}
    </div>
  `;
}

function emptyState(emoji, text) {
  return `<div class="empty"><span class="emoji">${emoji}</span>${text}</div>`;
}

function renderEventList(events, { emptyEmoji = "🎉", emptyText = "Событий нет", tappable = false, showDelete = false, showHide = false } = {}) {
  if (!events.length) return emptyState(emptyEmoji, emptyText);
  return events.map((e, i) => eventCard(e, { tappable, index: i, showDelete, showHide })).join("");
}

function renderGroupedByDate(events, { showDelete = false, showHide = false } = {}) {
  if (!events.length) return emptyState("🎉", "Событий нет");
  let html = "";
  let lastDate = null;
  events.forEach((e, i) => {
    if (e.date !== lastDate) {
      html += `<div class="date-heading">${dateHeading(e.date)}</div>`;
      lastDate = e.date;
    }
    html += eventCard(e, { index: i, showDelete, showHide });
  });
  return html;
}

function confirmHide(eventId, summary, onDone) {
  tg.showConfirm(`Скрыть «${summary}» только у себя? Остальные подписчики продолжат его видеть и получать напоминания.`, async (confirmed) => {
    if (!confirmed) return;
    try {
      await api("/api/events/hide", { method: "POST", body: JSON.stringify({ event_id: eventId }) });
      hapticNotify("success");
      tg.showAlert("Скрыто. Вернуть можно в разделе «Ещё».");
    } catch (e) {
      hapticNotify("error");
      tg.showAlert("Ошибка: " + e.message);
    }
    if (onDone) onDone();
  });
}

// Вешает обработчики на кнопки "открыть в Google Calendar", "скрыть" и
// "удалить", добавленные в eventCard() - вызывать после каждой вставки
// renderEventList()/renderGroupedByDate() в DOM.
function bindCardActions(onChanged) {
  content.querySelectorAll(".cal-link, .olympiad-link-btn").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      haptic("light");
      tg.openLink(btn.dataset.link);
    };
  });
  content.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      haptic("light");
      confirmDelete(btn.dataset.id, btn.dataset.summary, onChanged);
    };
  });
  content.querySelectorAll(".hide-btn").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      haptic("light");
      confirmHide(btn.dataset.id, btn.dataset.summary, onChanged);
    };
  });
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
    const [events, monthBlock] = await Promise.all([api("/api/events/today"), fetchMonthSummary()]);
    setSubtitle(events.length ? `${events.length} ${pluralEvents(events.length)}` : "Свободный день");
    content.innerHTML = monthBlock + subBtn + renderEventList(events, {
      emptyEmoji: "🎉", emptyText: "Событий на сегодня нет", showDelete: STATE.is_admin, showHide: true,
    });
    bindCardActions(showToday);
  } catch (e) {
    content.innerHTML = subBtn + emptyState("⚠️", "Не удалось загрузить: " + escapeHtml(e.message));
  }
  document.getElementById("sub-toggle").onclick = async () => {
    haptic("medium");
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
    content.innerHTML = renderGroupedByDate(events, { showDelete: STATE.is_admin, showHide: true });
    bindCardActions(showUpcoming);
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
    html += items.map((o, i) => `
      <div class="card" style="--i:${i}">
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
      haptic("medium");
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
        hapticNotify(parts.length ? "success" : "warning");
        tg.showAlert(parts.length ? parts.join("\n") : "Изменений не найдено");
      } catch (e) {
        hapticNotify("error");
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
      <button class="btn secondary" id="open-hidden">🙈 Скрытые события</button>
      ${emptyState("🔒", "Остальные настройки бота доступны только администратору.")}
    `;
    document.getElementById("open-hidden").onclick = () => { haptic("light"); showHiddenPicker(); };
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
    <button class="btn secondary" id="open-hidden">🙈 Скрытые события</button>
    <button class="btn danger" id="open-delete">🗑 Удалить событие из календаря</button>
  `;

  document.getElementById("save-settings").onclick = async () => {
    haptic("medium");
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
      hapticNotify("success");
      tg.showAlert("Сохранено! Интервал опроса и время сводки применятся в течение ~30 секунд.");
      showSettings();
    } catch (e) {
      hapticNotify("error");
      tg.showAlert("Не сохранено: " + e.message);
      btn.disabled = false;
    }
  };

  document.getElementById("open-hidden").onclick = () => { haptic("light"); showHiddenPicker(); };
  document.getElementById("open-delete").onclick = () => { haptic("light"); showDeletePicker(); };
}

async function showHiddenPicker() {
  titleEl.textContent = "Скрытые события";
  setSubtitle("Видны только вам");
  content.innerHTML = skeleton(2);
  let events;
  try {
    events = await api("/api/hidden_events");
  } catch (e) {
    content.innerHTML = emptyState("⚠️", "Ошибка: " + escapeHtml(e.message)) + backButton();
    bindBack();
    return;
  }

  if (!events.length) {
    content.innerHTML = emptyState("🙈", "У вас нет скрытых событий") + backButton();
  } else {
    content.innerHTML = events.map((e, i) => `
      <div class="card" style="--i:${i}">
        <div class="row-top"><span class="time">${escapeHtml(e.when)}</span></div>
        <div class="title">${escapeHtml(e.summary)}</div>
        <div class="row-actions">
          <button class="cal-link" data-id="${escapeHtml(e.id)}">↩️ Вернуть</button>
        </div>
      </div>
    `).join("") + backButton();
    content.querySelectorAll(".cal-link").forEach((btn) => {
      btn.onclick = async () => {
        haptic("light");
        try {
          await api("/api/events/unhide", { method: "POST", body: JSON.stringify({ event_id: btn.dataset.id }) });
          hapticNotify("success");
        } catch (e) {
          hapticNotify("error");
          tg.showAlert("Ошибка: " + e.message);
        }
        showHiddenPicker();
      };
    });
  }
  bindBack();
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
      card.onclick = () => {
        haptic("light");
        confirmDelete(card.dataset.id, card.querySelector(".title").textContent, showDeletePicker);
      };
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

function confirmDelete(eventId, summary, onDone) {
  tg.showConfirm(`Удалить «${summary}» из календаря? Это затронет всех подписчиков.`, async (confirmed) => {
    if (!confirmed) return;
    try {
      await api("/api/events/delete", { method: "POST", body: JSON.stringify({ event_id: eventId }) });
      hapticNotify("success");
      tg.showAlert("Событие удалено");
    } catch (e) {
      hapticNotify("error");
      tg.showAlert("Ошибка: " + e.message);
    }
    (onDone || showDeletePicker)();
  });
}

const TABS = { today: showToday, upcoming: showUpcoming, olympiads: showOlympiads, settings: showSettings };

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.onclick = () => {
    if (!btn.classList.contains("active")) haptic("light");
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    TABS[btn.dataset.tab]();
  };
});

// Обновляет текст обратного отсчёта на карточках раз в 20 секунд без
// повторного запроса к серверу - просто пересчитывает разницу во времени
// на уже отрисованных карточках (если текущая вкладка их не показывает,
// просто ничего не находит и не делает).
setInterval(() => {
  content.querySelectorAll(".countdown[data-start-ts]").forEach((el) => {
    const text = countdownText(el.dataset.startTs);
    if (text) {
      el.textContent = text;
    } else {
      el.remove();
    }
  });
}, 20000);

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
