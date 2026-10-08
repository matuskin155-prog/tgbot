const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();
// У приложения свой фирменный кавайный пастельный вид (не берём цвета из
// темы собеседника в Telegram) - только переключаем светлый/тёмный вариант
// вслед за самим Telegram, через data-theme на <html>. Цвета шапки и фона
// самого Telegram подгоняем под розовую шапку приложения (--header-bg и --bg
// в app.css), чтобы сверху не было чужой полоски.
const TG_COLORS = {
  light: { header: "#ffd3e6", bg: "#fff4f9" },
  dark: { header: "#4a2a5c", bg: "#22132c" },
};
function applyColorScheme() {
  const scheme = tg.colorScheme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = scheme;
  try {
    if (tg.setHeaderColor) tg.setHeaderColor(TG_COLORS[scheme].header);
    if (tg.setBackgroundColor) tg.setBackgroundColor(TG_COLORS[scheme].bg);
  } catch (e) { /* старые клиенты не умеют свои цвета */ }
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

function renderEventList(events, { emptyEmoji = "🌸", emptyText = "Событий нет", tappable = false, showDelete = false, showHide = false } = {}) {
  if (!events.length) return emptyState(emptyEmoji, emptyText);
  return events.map((e, i) => eventCard(e, { tappable, index: i, showDelete, showHide })).join("");
}

function renderGroupedByDate(events, { showDelete = false, showHide = false } = {}) {
  if (!events.length) return emptyState("🌸", "Событий нет");
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
      emptyEmoji: "🌸", emptyText: "Событий на сегодня нет", showDelete: STATE.is_admin, showHide: true,
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

// --- Интерактивный календарь (вкладка "Календарь") ---
// Вместо плоского списка "ближайших событий" - помесячная сетка дней с
// точками-индикаторами (золотая - олимпиада, сиреневая - обычное событие),
// по которой можно листать вперёд/назад и тапать день, чтобы увидеть его
// события снизу (те же карточки, что и в остальном приложении).

const MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
const WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

let calendarState = null; // { year, month, events, selectedDate, today, deadlines }

function pad2(n) {
  return String(n).padStart(2, "0");
}

function ymKey(year, month) {
  return `${year}-${pad2(month)}`;
}

function pluralDays(n) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return "дней";
  if (mod10 === 1) return "день";
  if (mod10 >= 2 && mod10 <= 4) return "дня";
  return "дней";
}

// Дата "дедлайна" события - последний день, когда ещё можно успеть (конец
// периода регистрации/отборочного этапа, а не его начало - если
// регистрация идёт с 1 по 20 ноября, важно именно 20-е, вне зависимости от
// того, началась она уже или нет). end_date уже посчитан на сервере в
// часовом поясе бота (см. _end_date в webapp/server.py) - здесь просто
// разбираем как календарную дату, без часовых поясов и вычитаний.
function deadlineDaysLeft(e) {
  const today0 = new Date();
  today0.setHours(0, 0, 0, 0);
  const d0 = new Date((e.end_date || e.date) + "T00:00:00");
  return Math.round((d0 - today0) / 86400000);
}

function deadlineUrgency(days) {
  if (days <= 2) return "urgent";
  if (days <= 10) return "soon";
  return "";
}

function deadlineLabel(days) {
  if (days <= 0) return "сегодня!";
  if (days === 1) return "завтра";
  return `${days} ${pluralDays(days)}`;
}

// Горизонтальная лента ближайших олимпиадных дедлайнов - главная польза
// вкладки "Календарь": не нужно листать месяцы, чтобы понять, что скоро
// горит. Тап по карточке переводит сетку месяца на день этого события.
function renderDeadlines(events) {
  if (!events || !events.length) return "";
  const items = events.map((e) => {
    const days = deadlineDaysLeft(e);
    const urgency = deadlineUrgency(days);
    return `
      <button type="button" class="deadline-chip ${urgency}" data-date="${escapeHtml(e.date)}">
        <span class="deadline-days">${deadlineLabel(days)}</span>
        <span class="deadline-name">${escapeHtml(e.summary)}</span>
      </button>
    `;
  }).join("");
  return `
    <div class="deadlines-block">
      <div class="deadlines-header">⏳ Ближайшие дедлайны олимпиад</div>
      <div class="deadlines-list">${items}</div>
    </div>
  `;
}

function bindDeadlineChips() {
  content.querySelectorAll(".deadline-chip").forEach((btn) => {
    btn.onclick = () => {
      haptic("light");
      const d = btn.dataset.date;
      const [y, m] = d.split("-").map(Number);
      calendarState.year = y;
      calendarState.month = m;
      calendarState.selectedDate = d;
      loadCalendarMonth();
    };
  });
}

// Сетка из 42 дней (6 недель), начиная с понедельника той недели, в которую
// попадает 1-е число - дни соседних месяцев показываются приглушённо, но
// тоже кликабельны (тап переключает на тот месяц). Если последняя неделя
// целиком из чужого месяца - обрезаем её, чтобы сетка была компактнее.
function buildMonthGrid(year, month, todayStr) {
  const firstOfMonth = new Date(year, month - 1, 1);
  const startOffset = (firstOfMonth.getDay() + 6) % 7;
  const gridStart = new Date(year, month - 1, 1 - startOffset);

  const cells = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    const dateStr = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
    cells.push({
      day: d.getDate(),
      dateStr,
      inMonth: d.getMonth() + 1 === month && d.getFullYear() === year,
      isToday: dateStr === todayStr,
      isWeekend: d.getDay() === 0 || d.getDay() === 6,
    });
  }
  if (cells.slice(35).every((c) => !c.inMonth)) cells.length = 35;
  return cells;
}

// Раскладывает события одной недели по "дорожкам", как в обычных
// календарях (Google Calendar и т.п.): непересекающиеся по дням события
// делят одну дорожку, пересекающиеся расходятся по разным, чтобы полоски с
// названиями не наезжали друг на друга. Даты в формате YYYY-MM-DD
// сравниваются просто как строки - этот формат сортируется лексикографически
// так же, как и по времени.
function packWeekLanes(weekDates, events) {
  const weekStart = weekDates[0];
  const weekEnd = weekDates[6];
  const items = [];
  for (const e of events) {
    const start = e.date;
    const end = e.end_date || e.date;
    if (end < weekStart || start > weekEnd) continue;
    const clampedStart = start < weekStart ? weekStart : start;
    const clampedEnd = end > weekEnd ? weekEnd : end;
    const colStart = weekDates.indexOf(clampedStart);
    const colEnd = weekDates.indexOf(clampedEnd);
    if (colStart === -1 || colEnd === -1) continue;
    items.push({ event: e, colStart, colEnd, dateStr: clampedStart });
  }
  items.sort((a, b) => a.colStart - b.colStart || (b.colEnd - b.colStart) - (a.colEnd - a.colStart));

  const lanes = [];
  for (const item of items) {
    let laneIndex = lanes.findIndex((lane) => lane.every((b) => item.colStart > b.colEnd || item.colEnd < b.colStart));
    if (laneIndex === -1) {
      lanes.push([]);
      laneIndex = lanes.length - 1;
    }
    lanes[laneIndex].push(item);
    item.lane = laneIndex;
  }
  return { items, laneCount: lanes.length };
}

function renderCalendarHeader(year, month) {
  return `
    <div class="cal-nav">
      <button type="button" class="cal-nav-btn" id="cal-prev" aria-label="Предыдущий месяц">‹</button>
      <div class="cal-nav-title">${MONTHS_NOM[month - 1]} ${year}</div>
      <button type="button" class="cal-nav-btn" id="cal-next" aria-label="Следующий месяц">›</button>
    </div>
  `;
}

// Показывает не абстрактные точки/полоски, а подписанные "плашки" событий
// прямо в сетке - ровно как в привычных календарях (Google Calendar и
// т.п.): название видно сразу, без тапа по дню. Многодневные олимпиадные
// окна растягиваются на всю свою длину внутри недели.
function renderCalendarGrid(cells, events, selectedDate) {
  const head = WEEKDAYS_SHORT.map((w, i) => `<div class="cal-weekday${i >= 5 ? " is-weekend" : ""}">${w}</div>`).join("");

  const weeksHtml = [];
  for (let i = 0; i < cells.length; i += 7) {
    const weekCells = cells.slice(i, i + 7);
    const weekDates = weekCells.map((c) => c.dateStr);

    const daysHtml = weekCells.map((c) => {
      const classes = ["cal-day"];
      if (!c.inMonth) classes.push("is-outside");
      if (c.isToday) classes.push("is-today");
      if (c.isWeekend) classes.push("is-weekend");
      if (c.dateStr === selectedDate) classes.push("is-selected");
      return `<button type="button" class="${classes.join(" ")}" data-date="${c.dateStr}"><span class="cal-day-num">${c.day}</span></button>`;
    }).join("");

    const { items, laneCount } = packWeekLanes(weekDates, events);
    const barsHtml = items.map((it) => {
      const kind = it.event.olympiad_url ? "olympiad" : "other";
      const icon = kind === "olympiad" ? "🏅 " : "";
      const span = it.colEnd - it.colStart + 1;
      const style = `grid-column:${it.colStart + 1} / span ${span}; grid-row:${it.lane + 1};`;
      return `<button type="button" class="cal-bar ${kind}" style="${style}" data-date="${it.dateStr}">${icon}${escapeHtml(it.event.summary)}</button>`;
    }).join("");
    const lanesHtml = laneCount
      ? `<div class="cal-week-lanes" style="grid-template-rows: repeat(${laneCount}, auto);">${barsHtml}</div>`
      : "";

    weeksHtml.push(`<div class="cal-week"><div class="cal-week-days">${daysHtml}</div>${lanesHtml}</div>`);
  }

  return `
    <div class="cal-grid">
      <div class="cal-weekdays">${head}</div>
      ${weeksHtml.join("")}
    </div>
    <div class="cal-legend"><span class="cal-legend-chip olympiad"></span> олимпиада &nbsp;&nbsp; <span class="cal-legend-chip other"></span> другое событие</div>
  `;
}

// Для олимпиадных окон день попадает в детали не только если это день
// НАЧАЛА события (как у обычных событий), но и любой день внутри всего
// многодневного окна - иначе тап по середине 20-дневной регистрации,
// которая явно подсвечена полоской в сетке, показывал бы пустоту.
function dayDetailEvents(events, dateStr) {
  const target = new Date(dateStr + "T00:00:00");
  return events.filter((e) => {
    if (e.date === dateStr) return true;
    if (!e.olympiad_url) return false;
    const start = new Date(e.date + "T00:00:00");
    const end = new Date((e.end_date || e.date) + "T00:00:00");
    return start <= target && target <= end;
  });
}

async function showCalendar() {
  titleEl.textContent = "Календарь";
  if (!calendarState) {
    const now = new Date();
    calendarState = { year: now.getFullYear(), month: now.getMonth() + 1, events: [], selectedDate: null, today: null, deadlines: null };
  }
  if (!calendarState.deadlines) {
    try {
      calendarState.deadlines = await api("/api/olympiads/deadlines");
    } catch (e) {
      calendarState.deadlines = [];
    }
  }
  await loadCalendarMonth();
}

// Полная перезагрузка и сетки месяца, и ленты дедлайнов - используется
// после скрытия/удаления события, чтобы оно пропало отовсюду сразу.
async function refreshCalendar() {
  calendarState.deadlines = null;
  await showCalendar();
}

async function loadCalendarMonth() {
  const { year, month, deadlines } = calendarState;
  setSubtitle("");
  content.innerHTML = renderDeadlines(deadlines) + renderCalendarHeader(year, month) + skeleton(3);
  bindCalendarNav();
  bindDeadlineChips();
  try {
    const data = await api(`/api/events/calendar?year=${year}&month=${month}`);
    calendarState.events = data.events;
    calendarState.today = data.today;
    const inThisMonth = calendarState.selectedDate && calendarState.selectedDate.slice(0, 7) === ymKey(year, month);
    if (!inThisMonth) {
      calendarState.selectedDate = data.today && data.today.slice(0, 7) === ymKey(year, month)
        ? data.today
        : `${ymKey(year, month)}-01`;
    }
    renderCalendarView();
  } catch (e) {
    content.innerHTML = renderDeadlines(deadlines) + renderCalendarHeader(year, month) + emptyState("⚠️", "Не удалось загрузить: " + escapeHtml(e.message));
    bindCalendarNav();
    bindDeadlineChips();
  }
}

function renderCalendarView() {
  const { year, month, events, selectedDate, today, deadlines } = calendarState;
  const cells = buildMonthGrid(year, month, today);
  const dayEvents = dayDetailEvents(events, selectedDate);
  const olympiadTotal = events.filter((e) => e.olympiad_url).length;
  setSubtitle(`${events.length} ${pluralEvents(events.length)} за месяц` + (olympiadTotal ? ` · ${olympiadTotal} олимпиад` : ""));

  content.innerHTML =
    renderDeadlines(deadlines) +
    renderCalendarHeader(year, month) +
    renderCalendarGrid(cells, events, selectedDate) +
    `<div class="cal-day-detail">
      <div class="date-heading">${dateHeading(selectedDate)}</div>
      ${renderEventList(dayEvents, { emptyEmoji: "🌸", emptyText: "Событий нет", showDelete: STATE.is_admin, showHide: true })}
    </div>`;

  bindCalendarNav();
  bindDeadlineChips();
  content.querySelectorAll(".cal-day, .cal-bar").forEach((btn) => {
    btn.onclick = () => {
      haptic("light");
      const d = btn.dataset.date;
      const [y, m] = d.split("-").map(Number);
      if (y !== calendarState.year || m !== calendarState.month) {
        calendarState.year = y;
        calendarState.month = m;
        calendarState.selectedDate = d;
        loadCalendarMonth();
      } else {
        calendarState.selectedDate = d;
        renderCalendarView();
      }
    };
  });
  bindCardActions(refreshCalendar);
}

function bindCalendarNav() {
  const prev = document.getElementById("cal-prev");
  const next = document.getElementById("cal-next");
  if (prev) prev.onclick = () => { haptic("light"); shiftCalendarMonth(-1); };
  if (next) next.onclick = () => { haptic("light"); shiftCalendarMonth(1); };
}

function shiftCalendarMonth(delta) {
  let { year, month } = calendarState;
  month += delta;
  if (month < 1) { month = 12; year -= 1; }
  if (month > 12) { month = 1; year += 1; }
  calendarState.year = year;
  calendarState.month = month;
  calendarState.selectedDate = null;
  loadCalendarMonth();
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

const TABS = { today: showToday, calendar: showCalendar, olympiads: showOlympiads, settings: showSettings };

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
