"""Grouped, deduplicated taxonomy of fields of study with a stable id per item.

Stored values stay free text (`fields` fact); `canonical_id` maps any spelling to
a stable item id through the alias table, and unknown spellings fall back to a
keyword group with a slug id, so a larger source list needs no code change.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

Labels = tuple[str, str, str]
"""(en, ru, uz)."""


@dataclass(frozen=True, slots=True)
class StudyGroup:
    """A group of study fields."""

    id: str
    labels: Labels


@dataclass(frozen=True, slots=True)
class StudyField:
    """A canonical field of study; `group` is a group id."""

    id: str
    group: str
    labels: Labels
    aliases: tuple[str, ...] = ()


GROUPS: tuple[StudyGroup, ...] = (
    StudyGroup(
        "computer_data",
        ("Computer & Data", "Компьютеры и данные", "Kompyuter va ma'lumotlar"),
    ),
    StudyGroup("engineering", ("Engineering", "Инженерия", "Muhandislik")),
    StudyGroup(
        "business_economics",
        ("Business & Economics", "Бизнес и экономика", "Biznes va iqtisodiyot"),
    ),
    StudyGroup(
        "natural_sciences",
        (
            "Natural Sciences & Math",
            "Естественные науки и математика",
            "Tabiiy fanlar va matematika",
        ),
    ),
    StudyGroup(
        "life_health",
        (
            "Life Sciences & Health",
            "Науки о жизни и здоровье",
            "Hayot fanlari va sogʻliq",
        ),
    ),
    StudyGroup(
        "social_sciences", ("Social Sciences", "Социальные науки", "Ijtimoiy fanlar")
    ),
    StudyGroup(
        "law_politics", ("Law & Politics", "Право и политика", "Huquq va siyosat")
    ),
    StudyGroup("humanities", ("Humanities", "Гуманитарные науки", "Gumanitar fanlar")),
    StudyGroup(
        "arts_design", ("Arts & Design", "Искусство и дизайн", "San'at va dizayn")
    ),
    StudyGroup(
        "architecture_planning",
        (
            "Architecture & Planning",
            "Архитектура и планирование",
            "Arxitektura va rejalashtirish",
        ),
    ),
    StudyGroup("education", ("Education", "Образование", "Ta'lim")),
    StudyGroup(
        "environment",
        ("Environment & Earth", "Окружающая среда и Земля", "Atrof-muhit va Yer"),
    ),
    StudyGroup(
        "interdisciplinary",
        (
            "Interdisciplinary & Liberal Arts",
            "Междисциплинарные и свободные искусства",
            "Fanlararo va liberal san'at",
        ),
    ),
)

_F = StudyField
FIELDS: tuple[StudyField, ...] = (
    _F(
        "computer_science",
        "computer_data",
        ("Computer Science", "Информатика", "Informatika"),
        (
            "computing",
            "computer sciences",
            "computer science and ai",
            "computer science and mathematics",
        ),
    ),
    _F(
        "information_systems",
        "computer_data",
        ("Information Systems", "Информационные системы", "Axborot tizimlari"),
    ),
    _F(
        "data_science",
        "computer_data",
        ("Data Science", "Наука о данных", "Maʼlumotlar fani"),
        ("data analytics", "data and ai", "artificial intelligence"),
    ),
    _F(
        "engineering",
        "engineering",
        ("Engineering", "Инженерия", "Muhandislik"),
        ("engineering sciences",),
    ),
    _F(
        "biomedical_engineering",
        "engineering",
        (
            "Biomedical Engineering",
            "Биомедицинская инженерия",
            "Biomedikal muhandislik",
        ),
    ),
    _F(
        "chemical_engineering",
        "engineering",
        ("Chemical Engineering", "Химическая инженерия", "Kimyo muhandisligi"),
        ("chemical engineering and biotechnology",),
    ),
    _F(
        "business",
        "business_economics",
        ("Business", "Бизнес", "Biznes"),
        ("business administration",),
    ),
    _F(
        "management",
        "business_economics",
        ("Management", "Менеджмент", "Menejment"),
        ("administrative sciences",),
    ),
    _F(
        "economics",
        "business_economics",
        ("Economics", "Экономика", "Iqtisodiyot"),
        (
            "economics and management",
            "economics and administrative sciences",
            "administrative sciences and economics",
        ),
    ),
    _F(
        "taxation",
        "business_economics",
        ("Taxation", "Налогообложение", "Soliq"),
        ("tax law", "tax law taxation"),
    ),
    _F(
        "mathematics",
        "natural_sciences",
        ("Mathematics", "Математика", "Matematika"),
        ("mathematical and physical sciences",),
    ),
    _F("physics", "natural_sciences", ("Physics", "Физика", "Fizika")),
    _F("chemistry", "natural_sciences", ("Chemistry", "Химия", "Kimyo")),
    _F(
        "natural_sciences",
        "natural_sciences",
        ("Natural Sciences", "Естественные науки", "Tabiiy fanlar"),
        ("science", "sciences"),
    ),
    _F(
        "biology",
        "life_health",
        ("Biology", "Биология", "Biologiya"),
        (
            "life sciences",
            "mathematical physical and life sciences",
        ),
    ),
    _F(
        "medicine",
        "life_health",
        ("Medicine & Health", "Медицина и здоровье", "Tibbiyot va sogʻliq"),
        (
            "medicine and health",
            "medicine and health sciences",
            "medical sciences",
            "health",
        ),
    ),
    _F("psychology", "social_sciences", ("Psychology", "Психология", "Psixologiya")),
    _F(
        "social_sciences",
        "social_sciences",
        ("Social Sciences", "Социальные науки", "Ijtimoiy fanlar"),
        ("social science",),
    ),
    _F("geography", "social_sciences", ("Geography", "География", "Geografiya")),
    _F("law", "law_politics", ("Law", "Право", "Huquq")),
    _F(
        "politics",
        "law_politics",
        ("Politics & Government", "Политика и государство", "Siyosat va davlat"),
        ("government", "political science"),
    ),
    _F("history", "humanities", ("History", "История", "Tarix")),
    _F(
        "literature_languages",
        "humanities",
        ("Literature & Languages", "Литература и языки", "Adabiyot va tillar"),
        ("english", "classics", "languages", "humanities and letters"),
    ),
    _F(
        "humanities",
        "humanities",
        ("Humanities", "Гуманитарные науки", "Gumanitar fanlar"),
        (
            "arts and humanities",
            "humanities and social sciences",
            "arts and social sciences",
        ),
    ),
    _F(
        "arts",
        "arts_design",
        ("Arts", "Искусство", "San'at"),
        ("fine arts", "arts tisch"),
    ),
    _F(
        "design", "arts_design", ("Design", "Дизайн", "Dizayn"), ("arts academics bxa",)
    ),
    _F(
        "music_performing",
        "arts_design",
        (
            "Music & Performing Arts",
            "Музыка и сценические искусства",
            "Musiqa va sahna san'ati",
        ),
        ("music and theater arts", "music and performing arts", "music", "drama"),
    ),
    _F(
        "architecture",
        "architecture_planning",
        ("Architecture", "Архитектура", "Arxitektura"),
        ("architecture and design", "architecture and planning", "built environment"),
    ),
    _F(
        "education",
        "education",
        ("Education", "Образование", "Ta'lim"),
        ("education and human development",),
    ),
    _F(
        "environmental_science",
        "environment",
        ("Environmental Science", "Экология", "Ekologiya"),
        (
            "environmental studies",
            "earth atmospheric and planetary sciences",
        ),
    ),
    _F(
        "liberal_arts",
        "interdisciplinary",
        ("Liberal Arts", "Свободные искусства", "Liberal san'at"),
        (
            "arts and sciences",
            "arts and science",
            "interdisciplinary",
            "interdisciplinary gallatin",
        ),
    ),
    _F(
        "urban_planning",
        "architecture_planning",
        ("Urban Planning", "Градостроительство", "Shaharsozlik"),
    ),
    _F("nursing", "life_health", ("Nursing", "Сестринское дело", "Hamshiralik")),
    _F("pharmacy", "life_health", ("Pharmacy", "Фармация", "Farmatsiya")),
    _F(
        "public_health",
        "life_health",
        ("Public Health", "Общественное здравоохранение", "Jamoat salomatligi"),
    ),
    _F(
        "dentistry",
        "life_health",
        ("Dentistry", "Стоматология", "Stomatologiya"),
    ),
    _F(
        "veterinary",
        "life_health",
        ("Veterinary Medicine", "Ветеринария", "Veterinariya"),
    ),
    _F(
        "kinesiology",
        "life_health",
        ("Kinesiology", "Кинезиология", "Kineziologiya"),
    ),
    _F(
        "nutrition",
        "life_health",
        ("Nutrition", "Питание и диетология", "Ovqatlanish"),
    ),
    _F(
        "neuroscience",
        "life_health",
        ("Neuroscience", "Нейронауки", "Neyrofanlar"),
    ),
    _F(
        "cognitive_science",
        "life_health",
        ("Cognitive Science", "Когнитивные науки", "Kognitiv fanlar"),
    ),
    _F(
        "biochemistry",
        "life_health",
        ("Biochemistry", "Биохимия", "Biokimyo"),
    ),
    _F(
        "marine_biology",
        "life_health",
        ("Marine Biology", "Морская биология", "Dengiz biologiyasi"),
    ),
    _F(
        "food_science",
        "life_health",
        ("Food Science", "Пищевые технологии", "Oziq-ovqat fanlari"),
    ),
    _F("statistics", "natural_sciences", ("Statistics", "Статистика", "Statistika")),
    _F("astronomy", "natural_sciences", ("Astronomy", "Астрономия", "Astronomiya")),
    _F(
        "software_engineering",
        "computer_data",
        ("Software Engineering", "Программная инженерия", "Dasturiy injiniring"),
    ),
    _F(
        "cybersecurity",
        "computer_data",
        ("Cybersecurity", "Кибербезопасность", "Kiberxavfsizlik"),
    ),
    _F(
        "electrical_engineering",
        "engineering",
        ("Electrical Engineering", "Электротехника", "Elektrotexnika"),
    ),
    _F(
        "mechanical_engineering",
        "engineering",
        ("Mechanical Engineering", "Машиностроение", "Mashinasozlik"),
    ),
    _F(
        "civil_engineering",
        "engineering",
        ("Civil Engineering", "Строительная инженерия", "Qurilish muhandisligi"),
    ),
    _F(
        "aerospace_engineering",
        "engineering",
        (
            "Aerospace Engineering",
            "Аэрокосмическая инженерия",
            "Aerokosmik muhandislik",
        ),
    ),
    _F(
        "industrial_engineering",
        "engineering",
        ("Industrial Engineering", "Промышленная инженерия", "Sanoat muhandisligi"),
    ),
    _F(
        "materials_engineering",
        "engineering",
        ("Materials Engineering", "Материаловедение", "Materiallar muhandisligi"),
    ),
    _F(
        "petroleum_engineering",
        "engineering",
        ("Petroleum Engineering", "Нефтегазовая инженерия", "Neft muhandisligi"),
    ),
    _F(
        "nuclear_engineering",
        "engineering",
        ("Nuclear Engineering", "Ядерная инженерия", "Yadro muhandisligi"),
    ),
    _F("aviation", "engineering", ("Aviation", "Авиация", "Aviatsiya")),
    _F("finance", "business_economics", ("Finance", "Финансы", "Moliya")),
    _F(
        "accounting",
        "business_economics",
        ("Accounting", "Бухгалтерский учёт", "Buxgalteriya hisobi"),
    ),
    _F("marketing", "business_economics", ("Marketing", "Маркетинг", "Marketing")),
    _F(
        "entrepreneurship",
        "business_economics",
        ("Entrepreneurship", "Предпринимательство", "Tadbirkorlik"),
    ),
    _F(
        "hospitality",
        "business_economics",
        (
            "Hospitality & Tourism",
            "Гостиничное дело и туризм",
            "Mehmonxona va turizm",
        ),
        ("hospitality management", "tourism"),
    ),
    _F(
        "supply_chain",
        "business_economics",
        ("Supply Chain", "Логистика и цепочки поставок", "Ta'minot zanjiri"),
    ),
    _F(
        "real_estate",
        "business_economics",
        ("Real Estate", "Недвижимость", "Koʻchmas mulk"),
    ),
    _F(
        "sports_management",
        "business_economics",
        ("Sports Management", "Менеджмент спорта", "Sport menejmenti"),
    ),
    _F(
        "international_relations",
        "law_politics",
        (
            "International Relations",
            "Международные отношения",
            "Xalqaro munosabatlar",
        ),
    ),
    _F(
        "criminology",
        "social_sciences",
        ("Criminology", "Криминология", "Kriminologiya"),
    ),
    _F(
        "social_work",
        "social_sciences",
        ("Social Work", "Социальная работа", "Ijtimoiy ish"),
    ),
    _F(
        "anthropology",
        "social_sciences",
        ("Anthropology", "Антропология", "Antropologiya"),
    ),
    _F(
        "sociology",
        "social_sciences",
        ("Sociology", "Социология", "Sotsiologiya"),
    ),
    _F(
        "philosophy",
        "humanities",
        ("Philosophy", "Философия", "Falsafa"),
    ),
    _F(
        "religious_studies",
        "humanities",
        ("Religious Studies", "Религиоведение", "Dinshunoslik"),
    ),
    _F(
        "archaeology",
        "humanities",
        ("Archaeology", "Археология", "Arxeologiya"),
    ),
    _F(
        "linguistics",
        "humanities",
        ("Linguistics", "Лингвистика", "Tilshunoslik"),
    ),
    _F(
        "creative_writing",
        "humanities",
        ("Creative Writing", "Литературное творчество", "Ijodiy yozuvchilik"),
    ),
    _F(
        "journalism",
        "humanities",
        ("Journalism", "Журналистика", "Jurnalistika"),
    ),
    _F(
        "communications",
        "humanities",
        ("Communications", "Коммуникации", "Kommunikatsiya"),
    ),
    _F(
        "media_studies",
        "humanities",
        ("Media Studies", "Медиаисследования", "Media tadqiqotlari"),
    ),
    _F(
        "area_studies",
        "interdisciplinary",
        ("Area Studies", "Регионоведение", "Hududshunoslik"),
    ),
    _F(
        "gender_studies",
        "interdisciplinary",
        ("Gender Studies", "Гендерные исследования", "Gender tadqiqotlari"),
    ),
    _F("film", "arts_design", ("Film", "Кино", "Kino")),
    _F(
        "theatre",
        "arts_design",
        ("Theatre", "Театральное искусство", "Teatr san'ati"),
    ),
    _F("dance", "arts_design", ("Dance", "Хореография", "Raqs san'ati")),
    _F("fashion", "arts_design", ("Fashion", "Мода", "Moda")),
    _F(
        "graphic_design",
        "arts_design",
        ("Graphic Design", "Графический дизайн", "Grafik dizayn"),
    ),
    _F(
        "game_design",
        "arts_design",
        ("Game Design", "Гейм-дизайн", "O'yin dizayni"),
    ),
    _F(
        "earth_sciences",
        "environment",
        ("Earth Sciences", "Науки о Земле", "Yer fanlari"),
    ),
    _F(
        "agriculture",
        "environment",
        ("Agriculture", "Сельское хозяйство", "Qishloq xoʻjaligi"),
    ),
)


def is_field_id(item_id: str) -> bool:
    """Whether `item_id` is a canonical id of the taxonomy."""
    return item_id in _BY_ID


_GENERIC = frozenset({"general"})
_PAREN = re.compile(r"\s*\([^)]*\)")
_NON_WORD = re.compile(r"[^a-z0-9]+")

_KEYWORD_GROUPS: tuple[tuple[str, str], ...] = (
    ("comput", "computer_data"),
    ("data", "computer_data"),
    ("engineer", "engineering"),
    ("business", "business_economics"),
    ("econom", "business_economics"),
    ("manage", "business_economics"),
    ("financ", "business_economics"),
    ("account", "business_economics"),
    ("math", "natural_sciences"),
    ("physic", "natural_sciences"),
    ("chemi", "natural_sciences"),
    ("biolog", "life_health"),
    ("medic", "life_health"),
    ("health", "life_health"),
    ("nurs", "life_health"),
    ("law", "law_politics"),
    ("politic", "law_politics"),
    ("history", "humanities"),
    ("lang", "humanities"),
    ("literat", "humanities"),
    ("philos", "humanities"),
    ("art", "arts_design"),
    ("design", "arts_design"),
    ("music", "arts_design"),
    ("architect", "architecture_planning"),
    ("educat", "education"),
    ("environ", "environment"),
    ("social", "social_sciences"),
    ("psych", "social_sciences"),
)


def normalize(raw: str) -> str:
    """Canonical spelling for alias lookup: no school suffix, `and`, singular."""
    s = _PAREN.sub("", raw).casefold().replace("&", " and ").replace("+", " ")
    s = _NON_WORD.sub(" ", s)
    words = [w for w in s.split() if w not in _GENERIC]
    return " ".join(words)


def _alias_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for item in FIELDS:
        for name in (item.labels[0], item.id.replace("_", " "), *item.aliases):
            table.setdefault(normalize(name), item.id)
    return table


_ALIASES = _alias_table()
_BY_ID = {f.id: f for f in FIELDS}
_GROUP_BY_ID = {g.id: g for g in GROUPS}


def _singular(key: str) -> str:
    return re.sub(r"\bsciences\b", "science", key)


@lru_cache(maxsize=4096)
def canonical_id(raw: str) -> str:
    """Stable item id of any stored spelling; unknown spellings get a slug id."""
    key = normalize(raw)
    hit = _ALIASES.get(key) or _ALIASES.get(_singular(key))
    if hit is not None:
        return hit
    if key.endswith(" sciences") or key.endswith(" science"):
        base = _ALIASES.get(key.rsplit(" ", 1)[0])
        if base is not None:
            return base
    return "x_" + (key.replace(" ", "_") or "other")


def group_of(item_id: str, raw: str = "") -> str:
    """Group id of an item; unknown items use keyword matching on the raw text."""
    known = _BY_ID.get(item_id)
    if known is not None:
        return known.group
    text = (raw or item_id.removeprefix("x_").replace("_", " ")).casefold()
    for needle, group in _KEYWORD_GROUPS:
        if needle in text:
            return group
    return "interdisciplinary"


def _label(labels: Labels, locale: str) -> str:
    return labels[{"ru": 1, "uz": 2}.get(locale, 0)]


def labels_of(item_id: str, raw: str, locale: str = "en") -> str:
    """Display label of an item; unknown items keep their first raw spelling."""
    known = _BY_ID.get(item_id)
    if known is not None:
        return _label(known.labels, locale)
    text = raw.strip()
    return text.title() if text.islower() else text


def canonical_names(raw_values: list[str]) -> tuple[str, ...]:
    """Deduplicated English labels of the canonical fields among the spellings."""
    seen: dict[str, str] = {}
    for raw in raw_values:
        cid = canonical_id(raw)
        if cid in _BY_ID:
            seen.setdefault(cid, labels_of(cid, raw))
    return tuple(sorted(seen.values(), key=str.casefold))


def build_taxonomy(locale: str = "en") -> list[dict[str, Any]]:
    """Groups with the canonical fields only, localized and sorted by label.

    Each group is {id, label, items: [{id, label}]}; empty groups are dropped.
    Scraped program names are not fields of study and never appear here.
    """
    items: dict[str, tuple[str, str]] = {f.id: (f.group, f.labels[0]) for f in FIELDS}
    names = {f.id: _label(f.labels, locale) for f in FIELDS}
    out: list[dict[str, Any]] = []
    for group in GROUPS:
        members = [
            {"id": cid, "label": names[cid]}
            for cid, (g, _) in items.items()
            if g == group.id
        ]
        if members:
            members.sort(key=lambda m: m["label"].casefold())
            out.append(
                {
                    "id": group.id,
                    "label": _label(group.labels, locale),
                    "items": members,
                }
            )
    return out
