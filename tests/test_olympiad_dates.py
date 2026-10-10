from datetime import date, timedelta

import pytest

from bot.olympiad_dates import extract_candidate_dates

# Фиксированное "сегодня", чтобы результат не зависел от дня запуска тестов.
TODAY = date(2026, 10, 10)


def _extract(text, **kwargs):
    return extract_candidate_dates(text, today=TODAY, **kwargs)


def _spans(text, **kwargs):
    """(начало, конец включительно, метка) - так проще читать ожидания,
    чем с исключающим концом, как его хранит CandidateDate."""
    return [(c.start, c.end - timedelta(days=1), c.label) for c in _extract(text, **kwargs)]


# --- Базовый разбор дат ---------------------------------------------------


def test_range_with_explicit_year():
    text = "Заключительный этап пройдёт с 15 по 20 ноября 2026 года в Москве."
    assert _spans(text) == [(date(2026, 11, 15), date(2026, 11, 20), None)]


def test_range_with_dash():
    assert _spans("Очный тур: 3–5 декабря.") == [(date(2026, 12, 3), date(2026, 12, 5), None)]


def test_month_name_is_case_insensitive():
    assert _spans("с 15 по 20 НОЯБРЯ") == [(date(2026, 11, 15), date(2026, 11, 20), None)]


def test_single_date_end_is_exclusive():
    (c,) = _extract("Результаты будут опубликованы 20 декабря.")
    assert c.start == date(2026, 12, 20)
    assert c.end == date(2026, 12, 21)
    assert c.label is None
    assert "20 декабря" in c.context


@pytest.mark.parametrize(
    "text",
    ["Срок подачи заявок: 01.12.2026", "Приём работ до 01.12.26"],
)
def test_numeric_dates(text):
    assert _spans(text) == [(date(2026, 12, 1), date(2026, 12, 1), None)]


def test_invalid_dates_are_ignored():
    assert _extract("Даты: 31 февраля и 30.02.2026.") == []


# --- Год и окно актуальности ----------------------------------------------


def test_date_without_year_that_already_passed_rolls_to_next_year():
    assert _spans("Итоги подведены 8 октября.") == [(date(2027, 10, 8), date(2027, 10, 8), None)]


def test_yesterday_without_year_stays_in_current_year():
    # Один день "запаса" в прошлое: вчерашняя дата - ещё не следующий год.
    assert _spans("Итоги подведены 9 октября.") == [(date(2026, 10, 9), date(2026, 10, 9), None)]


def test_old_dates_with_explicit_year_are_dropped():
    assert _extract("© 2019. Олимпиада проводилась 12 марта 2019 года.") == []


def test_dates_too_far_in_future_are_dropped():
    assert _extract("Следующий сезон начнётся 1 сентября 2028 года.") == []


def test_max_results_cap():
    text = " ".join(f"{day} ноября." for day in range(1, 15))
    assert len(_extract(text)) == 8
    assert len(_extract(text, max_results=3)) == 3


# --- Регистрация / отборочный этап как промежуток ------------------------


def test_registration_explicit_range():
    text = "Регистрация на олимпиаду открыта с 1 по 25 ноября."
    assert _spans(text) == [(date(2026, 11, 1), date(2026, 11, 25), "регистрация")]


def test_registration_two_dates_near_one_mention():
    text = "Регистрация участников: открытие 1 ноября, закрытие 25 ноября."
    assert _spans(text) == [(date(2026, 11, 1), date(2026, 11, 25), "регистрация")]


def test_registration_start_and_end_in_separate_sentences():
    text = (
        "Регистрация открывается 1 ноября. Приём заявок продлится долго. "
        "Регистрация завершается 25 ноября."
    )
    assert _spans(text) == [(date(2026, 11, 1), date(2026, 11, 25), "регистрация")]


def test_registration_start_and_end_in_separate_paragraphs():
    text = (
        "Регистрация открывается 1 ноября.\n\n"
        "Много текста об олимпиаде и её истории.\n\n"
        "Регистрация закрывается 25 ноября."
    )
    assert _spans(text) == [(date(2026, 11, 1), date(2026, 11, 25), "регистрация")]


def test_deadline_only_registration_keeps_label_without_inventing_interval():
    assert _spans("Регистрация до 25 ноября.") == [(date(2026, 11, 25), date(2026, 11, 25), "регистрация")]


def test_back_to_back_stage_ranges():
    text = "Регистрация проходит с 1 по 20 ноября. Отборочный этап пройдёт с 21 ноября по 5 декабря."
    assert _spans(text) == [
        (date(2026, 11, 1), date(2026, 11, 20), "регистрация"),
        (date(2026, 11, 21), date(2026, 12, 5), "отборочный этап"),
    ]


def test_back_to_back_stage_singles_do_not_leak_between_stages():
    # Конец регистрации (20 ноября) стоит по символам ближе к слову
    # "Отборочный", чем к "Регистрация", но принадлежит регистрации.
    text = (
        "Регистрация открывается 1 ноября и закрывается 20 ноября. "
        "Отборочный этап начнётся 22 ноября и завершится 10 декабря."
    )
    assert _spans(text) == [
        (date(2026, 11, 1), date(2026, 11, 20), "регистрация"),
        (date(2026, 11, 22), date(2026, 12, 10), "отборочный этап"),
    ]


def test_deadline_only_mentions_for_both_stages():
    text = "Регистрация до 25 ноября. Отборочный этап 1 декабря."
    assert _spans(text) == [
        (date(2026, 11, 25), date(2026, 11, 25), "регистрация"),
        (date(2026, 12, 1), date(2026, 12, 1), "отборочный этап"),
    ]


def test_stages_listed_out_of_order():
    text = "Отборочный этап: с 1 по 10 декабря.\n\nРегистрация: с 1 по 25 ноября."
    assert _spans(text) == [
        (date(2026, 12, 1), date(2026, 12, 10), "отборочный этап"),
        (date(2026, 11, 1), date(2026, 11, 25), "регистрация"),
    ]


def test_navigation_mention_does_not_steal_registration_range():
    text = (
        "Главная | Регистрация | Новости\n\n"
        "Олимпиада по математике\n\n"
        "Регистрация открыта с 1 по 25 ноября."
    )
    assert _spans(text) == [(date(2026, 11, 1), date(2026, 11, 25), "регистрация")]


# --- Известные недочёты эвристики -----------------------------------------
# Сейчас работают не так, как ожидалось бы. strict=True: когда разбор
# починят, тест начнёт проходить и упадёт как XPASS - тогда снять xfail.


@pytest.mark.xfail(strict=True, reason="дата финала через границу предложения склеивается с дедлайном регистрации")
def test_unrelated_date_after_sentence_boundary_is_not_paired_with_registration():
    text = "Регистрация до 25 ноября. Финал 15 марта."
    assert _spans(text) == [
        (date(2026, 11, 25), date(2026, 11, 25), "регистрация"),
        (date(2027, 3, 15), date(2027, 3, 15), None),
    ]


@pytest.mark.xfail(strict=True, reason="лишнее упоминание в навигации помечает соседнюю дату как регистрацию")
def test_navigation_mention_does_not_label_unrelated_date():
    text = (
        "Главная | Регистрация | Новости\n\n"
        "Олимпиада по математике\n\n"
        "Регистрация открыта с 1 по 25 ноября. Заключительный этап — 15 марта."
    )
    assert _spans(text) == [
        (date(2026, 11, 1), date(2026, 11, 25), "регистрация"),
        (date(2027, 3, 15), date(2027, 3, 15), None),
    ]
