import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class OlympiadSource:
    key: str
    name: str
    url: str


SOURCES: List[OlympiadSource] = [
    OlympiadSource("vysshaya_proba", "Высшая проба", "https://olymp.hse.ru/mmo/instr-reg"),
    OlympiadSource("izumrud", "Изумруд", "https://dovuz.urfu.ru/olymps/izumrud/registration"),
    OlympiadSource("vsesib", "Всесибирская олимпиада", "https://sesc.nsu.ru/olymp-vsesib/stages/"),
    OlympiadSource("nto", "НТО", "https://ntcontest.ru/"),
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
    OlympiadSource("belchonok", "Бельчонок", "http://dovuz.sfu-kras.ru/belchonok"),
]


_STOPWORDS = {"им", "по", "и", "для", "на", "в", "с", "из"}


def _content_words(name: str) -> List[str]:
    # Снимаем декоративные кавычки/скобки и пунктуацию («им.», «П.», «Д.»),
    # выкидываем служебные слова и инициалы — остаются только значимые слова,
    # по которым и будем сравнивать.
    cleaned = re.sub(r"[«»\"().,]", " ", name)
    return [w for w in cleaned.split() if len(w) > 2 and w.lower() not in _STOPWORDS]


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
        words = _content_words(source.name)
        if not words:
            continue
        # Одно короткое слово само по себе слишком легко случайно встретить
        # в несвязанном тексте - требуем либо несколько слов, либо одно, но
        # подлиннее. Исключение - аббревиатуры ЗАГЛАВНЫМИ буквами (НТО, МОШ):
        # случайно совпасть с обычным русским словом им намного сложнее, а
        # без этого исключения такие олимпиады не распознавались бы вообще
        # никогда, даже если в тексте написано прямо "НТО".
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
