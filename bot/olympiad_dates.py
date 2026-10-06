import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_MONTHS_PATTERN = "|".join(_MONTHS)

_RANGE_RE = re.compile(
    rf"(?:с\s+)?(\d{{1,2}})\s*(?:[-–—]|по)\s*(\d{{1,2}})\s+({_MONTHS_PATTERN})(?:\s+(\d{{4}}))?",
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(
    rf"(\d{{1,2}})\s+({_MONTHS_PATTERN})(?:\s+(\d{{4}}))?",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b")

# Ключевые слова этапов, для которых стоит собрать именно ПРОМЕЖУТОК (начало
# и конец), а не одну точку - у регистрации и отборочного тура почти всегда
# есть обе границы, часто упомянутые как две отдельные даты в разных
# предложениях, а не одним "с X по Y".
_REGISTRATION_RE = re.compile(r"регистрац\w*", re.IGNORECASE)
_QUALIFYING_RE = re.compile(r"отбор\w*", re.IGNORECASE)
_STAGE_LABELS = {
    "registration": "регистрация",
    "qualifying": "отборочный этап",
}
_STAGE_WINDOW_CHARS = 220

# Дальше ~18 месяцев считаем шумом (старые/неактуальные упоминания дат).
_FUTURE_WINDOW_DAYS = 548
_PAST_GRACE_DAYS = 1
_MAX_RESULTS = 8


@dataclass(frozen=True)
class CandidateDate:
    index: int
    start: date
    end: date  # исключительно (Google Calendar all-day: end = start + 1 для однодневных)
    context: str
    label: Optional[str] = None  # "регистрация" / "отборочный этап" / None


def _resolve_year(day: int, month: int, explicit_year: Optional[str], today: date) -> Optional[date]:
    if explicit_year:
        try:
            return date(int(explicit_year), month, day)
        except ValueError:
            return None
    # Год не указан явно - страница почти всегда имеет в виду ближайшее
    # будущее наступление этого дня/месяца, а не прошедшее.
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today - timedelta(days=_PAST_GRACE_DAYS):
            return candidate
    return None


def _context_snippet(text: str, start: int, end: int, radius: int = 60) -> str:
    snippet = text[max(0, start - radius) : end + radius]
    return re.sub(r"\s+", " ", snippet).strip()


def _collect_raw_tokens(text: str, today: date) -> List[dict]:
    """Все найденные даты как токены с позицией в тексте и границами
    (для диапазона low != high, для одиночной даты low == high)."""
    tokens: List[dict] = []
    covered = []  # диапазоны символов, уже занятые найденным "с X по Y"

    for m in _RANGE_RE.finditer(text):
        day1, day2, month_name, year = m.group(1), m.group(2), m.group(3), m.group(4)
        month = _MONTHS[month_name.lower()]
        low = _resolve_year(int(day1), month, year, today)
        high = _resolve_year(int(day2), month, year, today)
        if low is None or high is None or high < low:
            continue
        tokens.append({"start": m.start(), "end": m.end(), "low": low, "high": high, "kind": "range"})
        covered.append((m.start(), m.end()))

    def _is_covered(pos: int) -> bool:
        return any(s <= pos < e for s, e in covered)

    for m in _SINGLE_RE.finditer(text):
        if _is_covered(m.start()):
            continue
        day, month_name, year = m.group(1), m.group(2), m.group(3)
        month = _MONTHS[month_name.lower()]
        d = _resolve_year(int(day), month, year, today)
        if d is None:
            continue
        tokens.append({"start": m.start(), "end": m.end(), "low": d, "high": d, "kind": "single"})

    for m in _NUMERIC_RE.finditer(text):
        if _is_covered(m.start()):
            continue
        day_s, month_s, year_s = m.group(1), m.group(2), m.group(3)
        try:
            day_i, month_i = int(day_s), int(month_s)
            year_i = int(year_s) if len(year_s) == 4 else 2000 + int(year_s)
            d = date(year_i, month_i, day_i)
        except ValueError:
            continue
        tokens.append({"start": m.start(), "end": m.end(), "low": d, "high": d, "kind": "single"})

    tokens.sort(key=lambda t: t["start"])
    return tokens


def _group_stage_intervals(text: str, tokens: List[dict]) -> List[dict]:
    """Для "регистрация"/"отборочный этап" объединяет две ближайшие к
    ключевому слову даты в один промежуток (а не два отдельных события) -
    страницы часто пишут начало и конец этапа в разных местах текста, а не
    одним "с X по Y"."""
    consumed: set = set()
    grouped: List[dict] = []

    for stage_key, keyword_re in (("registration", _REGISTRATION_RE), ("qualifying", _QUALIFYING_RE)):
        for km in keyword_re.finditer(text):
            window_start = max(0, km.start() - _STAGE_WINDOW_CHARS)
            window_end = km.end() + _STAGE_WINDOW_CHARS
            nearby = sorted(
                (
                    (abs(t["start"] - km.start()), i)
                    for i, t in enumerate(tokens)
                    if i not in consumed and window_start <= t["start"] < window_end
                ),
            )[:2]
            if not nearby:
                continue

            closest_idx = nearby[0][1]
            if tokens[closest_idx]["kind"] == "range":
                # Ближайший токен уже сам диапазон ("с X по Y") - он уже
                # полностью описывает этап целиком, его не с чем "парить":
                # вторая по близости дата может относиться совсем к другому
                # этапу дальше в тексте.
                picked_indices = [closest_idx]
            elif len(nearby) >= 2:
                picked_indices = [i for _, i in nearby]
            else:
                continue  # одна одиночная дата рядом - не выдумываем промежуток

            picked = [tokens[i] for i in picked_indices]
            low = min(t["low"] for t in picked)
            high = max(t["high"] for t in picked)
            pos_start = min(t["start"] for t in picked)
            pos_end = max(t["end"] for t in picked)
            consumed.update(picked_indices)
            grouped.append(
                {
                    "start": pos_start,
                    "end": pos_end,
                    "low": low,
                    "high": high,
                    "label": _STAGE_LABELS[stage_key],
                }
            )

    leftover = [t for i, t in enumerate(tokens) if i not in consumed]
    for t in leftover:
        t.setdefault("label", None)

    combined = grouped + leftover
    combined.sort(key=lambda t: t["start"])
    return combined


def extract_candidate_dates(
    text: str, *, today: Optional[date] = None, max_results: int = _MAX_RESULTS
) -> List[CandidateDate]:
    """Ищет в тексте страницы упоминания конкретных дат (диапазоны вида
    "с 15 по 20 ноября", одиночные даты с русским названием месяца, формат
    дд.мм.гггг) и возвращает кандидатов в пределах ближайших ~18 месяцев.
    Для "регистрация"/"отборочный этап" две ближайшие к слову даты
    объединяются в один промежуток, а не два отдельных события.

    Это эвристика по тексту страницы, а НЕ надёжный разбор структуры
    конкретного сайта - может пропустить настоящую дату или найти случайное
    упоминание, не относящееся к проведению олимпиады. Поэтому вызывающий
    код помечает добавленные в календарь события как определённые
    автоматически, с просьбой сверить на сайте первоисточника.
    """
    if today is None:
        today = date.today()

    tokens = _collect_raw_tokens(text, today)
    combined = _group_stage_intervals(text, tokens)

    results: List[CandidateDate] = []
    window_end = today + timedelta(days=_FUTURE_WINDOW_DAYS)
    window_start = today - timedelta(days=_PAST_GRACE_DAYS)
    for index, t in enumerate(combined):
        if not (window_start <= t["low"] <= window_end):
            continue
        context = _context_snippet(text, t["start"], t["end"])
        results.append(
            CandidateDate(
                index=index,
                start=t["low"],
                end=t["high"] + timedelta(days=1),
                context=context,
                label=t.get("label"),
            )
        )
        if len(results) >= max_results:
            break

    return results
