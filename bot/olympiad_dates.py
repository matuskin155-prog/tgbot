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
# Если между датой и упоминанием слова есть граница предложения/абзаца -
# это упоминание, скорее всего, уже про ДРУГУЮ мысль, даже если по чистому
# числу символов оно ближе (частый случай: "...до 20 ноября. Отборочный
# этап..." - следующее предложение может оказаться ближе по символам, чем
# "своё" предыдущее). Не исключаем такое упоминание совсем (вдруг
# альтернативы нет), а сильно понижаем его приоритет при выборе владельца.
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?]\s|\n\s*\n")
_BOUNDARY_PENALTY = 10_000

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
    """Для "регистрация"/"отборочный этап" объединяет ближайшие к слову
    даты в один промежуток (а не отдельные события) - страницы часто пишут
    начало и конец этапа в разных местах текста, а не одним "с X по Y", и
    само ключевое слово нередко встречается на странице несколько раз
    (навигация, другие упоминания), не только там, где написаны даты.

    В три прохода, от самого надёжного к самому слабому - каждый следующий
    не трогает уже разобранные более надёжным проходом даты:

    1) Для каждого упоминания слова - если САМАЯ ближайшая к нему (ещё
       не занятая) дата сама по себе уже диапазон ("с X по Y") - он
       целиком и описывает этап, его не с чем "парить". Разбирается
       в первую очередь у всех упоминаний сразу - иначе случайное другое
       упоминание того же слова в навигации может перехватить этот диапазон
       раньше, чем до него "дойдёт очередь" у настоящего упоминания рядом.
    2) У оставшихся непустых упоминаний (ближайшая дата - не диапазон) -
       если рядом (ещё не занятых) находится две даты, объединяем их в
       промежуток. Иначе - только одна, откладываем как "половинку" этого
       этапа (не выбрасываем метку, но и не выдумываем промежуток).
    3) Половинки одного этапа от РАЗНЫХ упоминаний пытаемся спарить друг с
       другом - например, "регистрация открывается..." и "регистрация
       заканчивается..." в разных местах текста.

    Начиная со второго прохода (не раньше - см. ниже) каждая одиночная дата
    дополнительно закрепляется ровно за ОДНИМ этапом: тем, чьё упоминание
    слова ближе всего именно к ней. Без этого закрепления дата у конца
    одного этапа может "утечь" к соседнему упоминанию другого этапа, если
    тот текстуально стоит чуть ближе - частый случай, когда конец
    регистрации и начало отборочного этапа описаны соседними фразами.
    А вот для самого первого прохода (явные диапазоны) закрепление, наоборот,
    только мешает: диапазон однозначно описывает этап целиком сам по себе,
    и достаточно того, что он разбирается в порядке появления упоминаний
    по тексту - более ранее по тексту (обычно и по смыслу идущее первым)
    упоминание получает его первым."""
    stage_items = (("registration", _REGISTRATION_RE), ("qualifying", _QUALIFYING_RE))
    occurrences = {
        stage_key: [km.start() for km in keyword_re.finditer(text)] for stage_key, keyword_re in stage_items
    }
    all_positions = [(stage_key, pos) for stage_key, positions in occurrences.items() for pos in positions]

    token_owner: dict = {}
    for i, t in enumerate(tokens):
        best_stage, best_dist = None, None
        for stage_key, pos in all_positions:
            d = abs(t["start"] - pos)
            if d > _STAGE_WINDOW_CHARS:
                continue
            lo, hi = (t["start"], pos) if t["start"] < pos else (pos, t["start"])
            ranked_d = d + _BOUNDARY_PENALTY if _SENTENCE_BOUNDARY_RE.search(text, lo, hi) else d
            if best_dist is None or ranked_d < best_dist:
                best_stage, best_dist = stage_key, ranked_d
        token_owner[i] = best_stage

    consumed: set = set()
    grouped: List[dict] = []

    def _nearby_unconsumed(km_pos: int, limit: int, *, stage_key: Optional[str] = None) -> List[tuple]:
        window_start = max(0, km_pos - _STAGE_WINDOW_CHARS)
        window_end = km_pos + _STAGE_WINDOW_CHARS
        return sorted(
            (abs(t["start"] - km_pos), i)
            for i, t in enumerate(tokens)
            if i not in consumed
            and (stage_key is None or token_owner[i] == stage_key)
            and window_start <= t["start"] < window_end
        )[:limit]

    def _add_group(stage_key: str, indices: List[int]) -> None:
        consumed.update(indices)
        picked = [tokens[i] for i in indices]
        grouped.append(
            {
                "start": min(t["start"] for t in picked),
                "end": max(t["end"] for t in picked),
                "low": min(t["low"] for t in picked),
                "high": max(t["high"] for t in picked),
                "label": _STAGE_LABELS[stage_key],
            }
        )

    # Проход 1: явные диапазоны рядом со своим упоминанием - у всех
    # упоминаний сразу, прежде чем переходить к более слабым совпадениям.
    pending: dict = {"registration": [], "qualifying": []}
    for stage_key, _ in stage_items:
        for km_pos in occurrences[stage_key]:
            nearby = _nearby_unconsumed(km_pos, limit=1)
            if nearby and tokens[nearby[0][1]]["kind"] == "range":
                _add_group(stage_key, [nearby[0][1]])
            else:
                pending[stage_key].append(km_pos)

    # Проход 2: из оставшегося - пары дат рядом с одним упоминанием, либо
    # одиночная "половинка" на потом.
    singles_by_stage: dict = {"registration": [], "qualifying": []}
    for stage_key, _ in stage_items:
        for km_pos in pending[stage_key]:
            nearby = _nearby_unconsumed(km_pos, limit=2, stage_key=stage_key)
            if not nearby:
                continue
            if len(nearby) >= 2:
                _add_group(stage_key, [nearby[0][1], nearby[1][1]])
            else:
                singles_by_stage[stage_key].append(nearby[0][1])

    # Проход 3: спариваем половинки одного этапа от разных упоминаний.
    for stage_key, singles in singles_by_stage.items():
        available = sorted(i for i in singles if i not in consumed)
        for idx_a, idx_b in zip(available[::2], available[1::2]):
            _add_group(stage_key, [idx_a, idx_b])
        if len(available) % 2:
            # Нечётная одна половинка осталась без пары - не выдумываем
            # промежуток из воздуха, но метку этапа сохраняем.
            _add_group(stage_key, [available[-1]])

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
