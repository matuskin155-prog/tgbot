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


def extract_candidate_dates(
    text: str, *, today: Optional[date] = None, max_results: int = _MAX_RESULTS
) -> List[CandidateDate]:
    """Ищет в тексте страницы упоминания конкретных дат (диапазоны вида
    "с 15 по 20 ноября", одиночные даты с русским названием месяца, формат
    дд.мм.гггг) и возвращает кандидатов в пределах ближайших ~18 месяцев.

    Это эвристика по тексту страницы, а НЕ надёжный разбор структуры
    конкретного сайта - может пропустить настоящую дату или найти случайное
    упоминание, не относящееся к проведению олимпиады. Поэтому вызывающий
    код помечает добавленные в календарь события как определённые
    автоматически, с просьбой сверить на сайте первоисточника.
    """
    if today is None:
        today = date.today()

    matches = []  # (start_pos, end_pos, start_date, end_date_exclusive)
    covered = []  # диапазоны символов, уже занятые найденным диапазоном дат

    for m in _RANGE_RE.finditer(text):
        day1, day2, month_name, year = m.group(1), m.group(2), m.group(3), m.group(4)
        month = _MONTHS[month_name.lower()]
        start = _resolve_year(int(day1), month, year, today)
        end_day = _resolve_year(int(day2), month, year, today)
        if start is None or end_day is None or end_day < start:
            continue
        matches.append((m.start(), m.end(), start, end_day + timedelta(days=1)))
        covered.append((m.start(), m.end()))

    def _is_covered(pos: int) -> bool:
        return any(s <= pos < e for s, e in covered)

    for m in _SINGLE_RE.finditer(text):
        if _is_covered(m.start()):
            continue
        day, month_name, year = m.group(1), m.group(2), m.group(3)
        month = _MONTHS[month_name.lower()]
        start = _resolve_year(int(day), month, year, today)
        if start is None:
            continue
        matches.append((m.start(), m.end(), start, start + timedelta(days=1)))

    for m in _NUMERIC_RE.finditer(text):
        if _is_covered(m.start()):
            continue
        day_s, month_s, year_s = m.group(1), m.group(2), m.group(3)
        try:
            day_i, month_i = int(day_s), int(month_s)
            year_i = int(year_s) if len(year_s) == 4 else 2000 + int(year_s)
            start = date(year_i, month_i, day_i)
        except ValueError:
            continue
        matches.append((m.start(), m.end(), start, start + timedelta(days=1)))

    matches.sort(key=lambda item: item[0])

    results: List[CandidateDate] = []
    window_end = today + timedelta(days=_FUTURE_WINDOW_DAYS)
    window_start = today - timedelta(days=_PAST_GRACE_DAYS)
    for index, (pos_start, pos_end, start, end) in enumerate(matches):
        if not (window_start <= start <= window_end):
            continue
        context = _context_snippet(text, pos_start, pos_end)
        results.append(CandidateDate(index=index, start=start, end=end, context=context))
        if len(results) >= max_results:
            break

    return results
