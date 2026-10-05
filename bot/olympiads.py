from dataclasses import dataclass
from typing import List


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
    OlympiadSource("innagrika", "Иннагрика", "https://innagrika.ru/"),
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
