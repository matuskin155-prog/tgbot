import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    # Только для подсказок типов - реальный импорт втянул бы google-api-
    # python-client в модуль, у которого иначе нет таких зависимостей.
    from .google_calendar import CalendarEvent


@dataclass(frozen=True)
class OlympiadSource:
    key: str
    name: str
    url: str
    # Дополнительные варианты названия (опечатки, короткие формы), по
    # которым тоже нужно узнавать олимпиаду в вручную вписанных событиях -
    # например, встреченная опечатка "Бельченок" вместо "Бельчонок".
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    # False - олимпиаду больше не нужно автоматически проверять (парсить
    # сайт, следить за новыми датами) и не нужно показывать в списке
    # отслеживаемых, но события по ней всё ещё нужно УЗНАВАТЬ в календаре
    # (match_source_by_text ниже смотрит на весь SOURCES, а не только на
    # отслеживаемые) - например, Иннагрика: биологическая олимпиада, по
    # явному выбору больше не парсится, но уже вписанные/будущие вручную
    # события по ней по-прежнему должны помечаться как олимпиада.
    auto_check: bool = True


SOURCES: List[OlympiadSource] = [
    OlympiadSource("vysshaya_proba", "Высшая проба", "https://olymp.hse.ru/mmo/instr-reg"),
    OlympiadSource("izumrud", "Изумруд", "https://dovuz.urfu.ru/olymps/izumrud/registration"),
    OlympiadSource("vsesib", "Всесибирская олимпиада", "https://sesc.nsu.ru/olymp-vsesib/stages/"),
    OlympiadSource("nto", "НТО", "https://ntcontest.ru/"),
    OlympiadSource(
        "innagrika", "Иннагрика", "https://innagrika.ru/", auto_check=False
    ),
    OlympiadSource(
        "sechenovskaya",
        "Сеченовская олимпиада",
        "https://www.sechenov.ru/univers/structure/facultie/dovuz/olimpiady/",
    ),
    OlympiadSource(
        "bibn", "Будущие исследователи — будущее науки", "https://bibn.unn.ru/"
    ),
    OlympiadSource(
        "sarkisov",
        "Химическая олимпиада им. П. Д. Саркисова",
        "https://www.muctr.ru/abitur/school/sarkisov/osnovnaya-informatsiya/",
    ),
    OlympiadSource("kfu_mpo", "КФУ (МПО)", "https://malun.kpfu.ru/mpo"),
    OlympiadSource("yunye_talanty", "Юные таланты", "https://chemolymp.narod.ru/"),
    OlympiadSource("mosh", "МОШ", "https://мош.цпм.рф/"),
    OlympiadSource("mendeleev", "«Потомки Менделеева»", "https://malun.kpfu.ru/mendeleev"),
    OlympiadSource("granit_nauki", "«Гранит науки»", "http://ogn.spmi.ru/"),
    OlympiadSource("lomonosov", "«Ломоносов»", "http://olymp.msu.ru/"),
    OlympiadSource("phystech", "Физтех", "https://olymp-online.mipt.ru/"),
    OlympiadSource("shag_v_buduschee", "Шаг в будущее", "https://olymp.bmstu.ru/"),
    OlympiadSource("spbgu", "СПбГУ", "https://olympiada.spbu.ru/"),
    OlympiadSource("oho", "Открытая химическая олимпиада", "http://oho.misis.ru/"),
    OlympiadSource("gazprom", "Газпром", "https://olympiad.gazprom.ru/"),
    OlympiadSource(
        "pirogovskaya",
        "Пироговская олимпиада",
        "https://rsmu.ru/academics/for-school-students/pirogov-olimpiada",
    ),
    OlympiadSource(
        "spb_chem",
        "Санкт-Петербургская олимпиада по химии",
        "http://olymp.academtalant.ru/chemspb",
    ),
    OlympiadSource("turlom", "Турнир Ломоносова", "http://турлом.цпм.рф/"),
    OlympiadSource(
        "belchonok", "Бельчонок", "http://dovuz.sfu-kras.ru/belchonok",
        aliases=("Бельченок",),  # встреченная опечатка в вручную вписанном событии
    ),
]

# Только те олимпиады, чьи сайты бот реально парсит/перепроверяет и
# показывает в списке отслеживаемых - используется везде, где речь о
# самой ПРОВЕРКЕ (автоматической или по кнопке), в отличие от SOURCES
# целиком, который нужен ещё и для узнавания olimpiad по названию события
# (match_source_by_text ниже) - это не одно и то же: олимпиаду можно
# перестать проверять, но всё ещё узнавать по названию.
TRACKED_SOURCES: List[OlympiadSource] = [s for s in SOURCES if s.auto_check]


_STOPWORDS = {"им", "по", "и", "для", "на", "в", "с", "из"}
# "Олимпиада" само по себе ничего не различает - оно есть в названии почти
# каждого источника, а в коротком вручную вписанном событии ("Регистрация
# "Сеченовская"") его естественно опускают, раз и так понятно, что речь об
# олимпиаде. Требовать его наравне с остальными словами только мешает -
# убираем из сравнения (но оставляем остальные слова обязательными).
_GENERIC_WORDS = {"олимпиада", "олимпиады", "олимпиаду", "олимпиад", "олимпиаде", "олимпиадой"}


def _content_words(name: str) -> List[str]:
    # Снимаем декоративные кавычки/скобки и пунктуацию («им.», «П.», «Д.»),
    # выкидываем служебные слова и инициалы — остаются только значимые слова,
    # по которым и будем сравнивать.
    cleaned = re.sub(r"[«»\"().,]", " ", name)
    words = [w for w in cleaned.split() if len(w) > 2 and w.lower() not in _STOPWORDS]
    # "Олимпиада" убираем, только если в названии есть другие значимые
    # слова - если это ВСЁ название целиком, фильтровать нечем.
    without_generic = [w for w in words if w.lower() not in _GENERIC_WORDS]
    return without_generic or words


def _word_stem_pattern(word: str) -> str:
    # Русский язык падежный — "олимпиада"/"олимпиаду"/"олимпиады" и подобное
    # не совпадут буквально. Отрезаем правдоподобную длину окончания и
    # досопоставляем остаток любыми буквами, вместо точного сравнения слова.
    stem = word[:-2] if len(word) > 6 else word[:-1] if len(word) > 4 else word
    return re.escape(stem) + r"\w*"


def match_source_by_text(text: Optional[str]) -> Optional[OlympiadSource]:
    """Пытается узнать в произвольном тексте (например, названии события,
    вписанного в календарь вручную) одну из отслеживаемых олимпиад —
    по совпадению ВСЕХ значимых слов названия (в любом порядке, с учётом
    падежных окончаний), без учёта регистра.

    Это текстовое совпадение, а не надёжная привязка - может пропустить
    сильно сокращённое название или (реже) случайно сработать на
    не связанном тексте. Если подошло несколько источников — берётся тот,
    у которого совпавшее название длиннее (более специфичное)."""
    if not text:
        return None

    best: Optional[OlympiadSource] = None
    best_score = 0
    for source in SOURCES:
        for name in (source.name, *source.aliases):
            words = _content_words(name)
            if not words:
                continue
            # Одно короткое слово само по себе слишком легко случайно
            # встретить в несвязанном тексте - требуем либо несколько слов,
            # либо одно, но подлиннее. Исключение - аббревиатуры ЗАГЛАВНЫМИ
            # буквами (НТО, МОШ): случайно совпасть с обычным русским словом
            # им намного сложнее, а без этого исключения такие олимпиады не
            # распознавались бы вообще никогда, даже если в тексте написано
            # прямо "НТО".
            if len(words) == 1 and len(words[0]) < 5 and not (
                len(words[0]) >= 3 and words[0].isupper()
            ):
                continue
            if all(
                re.search(r"(?<!\w)" + _word_stem_pattern(w) + r"(?!\w)", text, re.IGNORECASE)
                for w in words
            ):
                score = sum(len(w) for w in words)
                if score > best_score:
                    best = source
                    best_score = score
    return best


def olympiad_url_for(event: "CalendarEvent") -> Optional[str]:
    """Ссылка на сайт олимпиады для календарного события - либо записанная
    ботом при автосоздании события (надёжный путь), либо, если её нет
    (событие вписано в календарь вручную), распознанная по названию события
    среди отслеживаемых олимпиад (см. match_source_by_text выше -
    текстовое совпадение, не гарантия). Общая для Mini App (показать
    бейдж/ссылку на карточке) и бота (отличить олимпиадное дедлайн-событие
    для напоминаний о закрытии регистрации/отборочного этапа)."""
    url = event.extended_properties.get("tgbot_olympiad_url")
    if url:
        return url
    source = match_source_by_text(event.summary)
    return source.url if source else None
