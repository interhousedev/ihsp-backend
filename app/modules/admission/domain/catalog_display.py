"""Human-ready catalog output: highlights, clean deadlines, facets, logo defaults."""

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from app.modules.admission.domain.chooser import CatalogInstitution


LOCALES: Final = ("en", "ru", "uz")
Opt = dict[str, tuple[str, str, str]]
"""value -> (en, ru, uz)."""

SETTING: Final[Opt] = {
    "urban": ("Urban", "Город", "Shahar"),
    "suburban": ("Suburban", "Пригород", "Shahar atrofi"),
    "rural": ("Rural", "Сельская местность", "Qishloq"),
}
INSTITUTION_TYPE: Final[Opt] = {
    "public": ("Public", "Государственный", "Davlat"),
    "private": ("Private", "Частный", "Xususiy"),
}
TEST_POLICY: Final[Opt] = {
    "required": ("Tests required", "Тесты обязательны", "Testlar majburiy"),
    "optional": ("Test-optional", "Тесты по желанию", "Testlar ixtiyoriy"),
    "blind": ("Test-blind", "Тесты не учитываются", "Testlar hisobga olinmaydi"),
    "flexible": ("Test-flexible", "Гибкая политика тестов", "Testlar moslashuvchan"),
    "not_applicable": ("No tests", "Тесты не нужны", "Testlar kerak emas"),
}
AID_BASIS: Final[Opt] = {
    "need_blind_full": (
        "Need-blind, meets full need",
        "Без учёта нужды, покрывает полную нужду",
        "Ehtiyojni hisobga olmaydi, toʻliq qoplaydi",
    ),
    "need_blind": (
        "Need-blind for internationals",
        "Без учёта нужды для иностранцев",
        "Xorijliklar uchun ehtiyojni hisobga olmaydi",
    ),
    "need_aware": (
        "Need-aware for internationals",
        "С учётом нужды для иностранцев",
        "Xorijliklar uchun ehtiyoj hisobga olinadi",
    ),
    "need_based": (
        "Need-based aid",
        "Помощь по нужде",
        "Ehtiyojga asoslangan yordam",
    ),
    "merit_only": ("Merit aid only", "Только за достижения", "Faqat yutuqlar uchun"),
    "none": ("No aid", "Без помощи", "Yordam yoʻq"),
}
PLAN: Final[Opt] = {
    "ED": ("Early Decision", "Early Decision", "Early Decision"),
    "ED2": ("Early Decision II", "Early Decision II", "Early Decision II"),
    "EA": ("Early Action", "Early Action", "Early Action"),
    "REA": (
        "Restrictive Early Action",
        "Restrictive Early Action",
        "Restrictive Early Action",
    ),
    "SCEA": (
        "Single-Choice Early Action",
        "Single-Choice Early Action",
        "Single-Choice Early Action",
    ),
    "RD": ("Regular Decision", "Regular Decision", "Regular Decision"),
    "ROLLING": ("Rolling", "Скользящий приём", "Surunkali qabul"),
    "OTHER": ("Deadline", "Срок", "Muddat"),
}
PLAN_SHORT: Final = {"ROLLING": ("Rolling", "Скольз.", "Surunkali")}
_KEYS: Final[dict[str, tuple[str, str, str]]] = {
    "setting": ("Setting", "Окружение", "Joylashuv"),
    "institution_type": ("Type", "Тип", "Turi"),
    "test_policy": ("Tests", "Тесты", "Testlar"),
    "acceptance_rate": ("Acceptance rate", "Доля принятых", "Qabul foizi"),
    "intl_tuition": (
        "International tuition",
        "Обучение для иностранцев",
        "Xorijliklar uchun oʻqish",
    ),
    "aid_basis": ("Financial aid", "Финансовая помощь", "Moliyaviy yordam"),
}
_MONTHS: Final = (
    ("Jan", "янв", "yan"),
    ("Feb", "фев", "fev"),
    ("Mar", "мар", "mar"),
    ("Apr", "апр", "apr"),
    ("May", "мая", "may"),
    ("Jun", "июн", "iyn"),
    ("Jul", "июл", "iyl"),
    ("Aug", "авг", "avg"),
    ("Sep", "сен", "sen"),
    ("Oct", "окт", "okt"),
    ("Nov", "ноя", "noy"),
    ("Dec", "дек", "dek"),
)
CYCLE_TERMS: Final = {"en": "intake", "ru": "набор", "uz": "qabul"}
MERIT_INTL: Final = (
    "Merit aid for internationals",
    "Стипендии за достижения для иностранцев",
    "Xorijliklar uchun yutuq stipendiyalari",
)
NO_YEAR_NOTE: Final = re.compile(
    r"(page|source)\s+(prints|shows)\s+no\s+year|treated as \d{4}-\d{2}|"
    r"year (not stated|inferred)|date assumed",
    re.I,
)


def _loc(locale: str) -> int:
    return {"ru": 1, "uz": 2}.get(locale, 0)


def option_label(options: Opt, value: str, locale: str) -> str:
    """Localised label of an option value; unknown values are shown as stored."""
    labels = options.get(value)
    return labels[_loc(locale)] if labels else value.replace("_", " ").capitalize()


def effective_aid_basis(inst: "CatalogInstitution") -> str | None:
    """The aid basis of the policy row, else of the cited fact."""
    if inst.aid_basis:
        return inst.aid_basis
    f = inst.fact("aid_basis")
    return str(f.value) if f is not None else None


def effective_merit(inst: "CatalogInstitution") -> bool | None:
    """Merit aid for internationals: the policy row, else the cited fact."""
    if inst.merit_available is not None:
        return inst.merit_available
    f = inst.fact("merit_for_internationals")
    return bool(f.value) if f is not None else None


def _money(value: Any, currency: str = "USD") -> str:
    n = int(Decimal(str(value)))
    sym = "$" if currency == "USD" else currency + " "
    return f"{sym}{n:,}".replace(",", " ")


def _rate(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    lo, hi = value.get("min"), value.get("max")
    if lo is None and hi is None:
        return None
    lo, hi = (hi if lo is None else lo), (lo if hi is None else hi)
    return f"{lo:g}%" if lo == hi else f"{lo:g}-{hi:g}%"


def highlights(inst: "CatalogInstitution", locale: str = "en") -> list[dict[str, str]]:
    """Ready-to-show {key, label, value_text} lines; missing facts are skipped."""
    i = _loc(locale)
    out: list[dict[str, str]] = []

    def add(key: str, text: str | None) -> None:
        if text:
            out.append({"key": key, "label": _KEYS[key][i], "value_text": text})

    for key, options in (
        ("setting", SETTING),
        ("institution_type", INSTITUTION_TYPE),
        ("test_policy", TEST_POLICY),
    ):
        fact = inst.fact("city_type" if key == "setting" else key)
        if fact is not None:
            add(key, option_label(options, str(fact.value), locale))
    rate = inst.fact("acceptance_rate")
    add("acceptance_rate", _rate(rate.value) if rate is not None else None)
    tuition = inst.fact("intl_tuition_usd")
    if tuition is not None and isinstance(tuition.value, (int, float, str)):
        add("intl_tuition", _money(tuition.value) + " / " + _YEAR[i])
    basis = effective_aid_basis(inst)
    parts = [option_label(AID_BASIS, basis, locale)] if basis else []
    if effective_merit(inst):
        parts.append(MERIT_INTL[i])
    add("aid_basis", "; ".join(parts))
    return out


_YEAR: Final = ("year", "год", "yil")


def _parse_date(v: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _short_date(d: dt.date, locale: str) -> str:
    return f"{d.day} {_MONTHS[d.month - 1][_loc(locale)]}"


_NOTIFY_ISO = re.compile(
    r"(?:announcement|results?|notified(?:\s+by|\s+on)?)\s+(\d{4}-\d{2}-\d{2})", re.I
)
_NOTIFY_MD = re.compile(
    r"notified(?:\s+by|\s+on)?\s+([A-Z][a-z]{2})[a-z]*\s+(\d{1,2})", re.I
)


def notify_by(note: str | None, deadline: dt.date | None) -> dt.date | None:
    """Notification date found in a note ("Notified Dec 15"), else None."""
    if not note:
        return None
    m = _NOTIFY_ISO.search(note)
    if m:
        return _parse_date(m.group(1))
    m = _NOTIFY_MD.search(note)
    if m is None or deadline is None:
        return None
    names = [x[0].casefold() for x in _MONTHS]
    mon = m.group(1).casefold()
    if mon not in names:
        return None
    month = names.index(mon) + 1
    year = deadline.year + (1 if month < deadline.month else 0)
    try:
        return dt.date(year, month, int(m.group(2)))
    except ValueError:
        return None


def clean_note(note: str | None) -> str | None:
    """Drop parser-style remarks (no year printed, treated as ...) from a note."""
    if not note:
        return None
    kept = [
        s.strip()
        for s in re.split(r"(?<=[.;])\s+", note)
        if s.strip() and not NO_YEAR_NOTE.search(s)
    ]
    return " ".join(kept) or None


def clean_deadlines(raw: Any, locale: str = "en") -> list[dict[str, Any]]:
    """Structured deadlines, by date.

    Items: {plan, date, notify_by, cycle, binding, time_zone, label_short}.

    `raw` is the stored `deadlines` fact; notes never leave this function.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for x in raw:
        if not isinstance(x, dict) or not x.get("plan"):
            continue
        plan = str(x["plan"])
        date = _parse_date(x.get("date")) if x.get("date") else None
        short = PLAN_SHORT.get(plan, (plan,) * 3)[_loc(locale)]
        if plan == "OTHER":
            short = PLAN["OTHER"][_loc(locale)]
        label = f"{short} · {_short_date(date, locale)}" if date else short
        out.append(
            {
                "plan": plan,
                "date": date,
                "notify_by": notify_by(x.get("note"), date),
                "cycle": x.get("cycle"),
                "binding": x["binding"] if isinstance(x.get("binding"), bool) else None,
                "time_zone": x.get("time_zone") or None,
                "label_short": label,
            }
        )
    out.sort(key=lambda d: (d["date"] is None, d["date"] or dt.date.max))
    return out


def has_deadline(
    inst: "CatalogInstitution", plan: str | None, cycle: str | None
) -> bool:
    """Whether a stored deadline has the plan and (or) the cycle."""
    f = inst.fact("deadlines")
    rows = f.value if f is not None and isinstance(f.value, list) else []
    return any(
        isinstance(x, dict)
        and (plan is None or x.get("plan") == plan)
        and (cycle is None or str(x.get("cycle")) == cycle)
        for x in rows
    )


def deadline_cycles(institutions: list["CatalogInstitution"]) -> list[str]:
    """Distinct deadline cycles of the catalog, newest first."""
    seen: set[str] = set()
    for inst in institutions:
        f = inst.fact("deadlines")
        for x in f.value if f is not None and isinstance(f.value, list) else []:
            if isinstance(x, dict) and x.get("cycle"):
                seen.add(str(x["cycle"]))
    return sorted(seen, reverse=True)


# --- logo -------------------------------------------------------------

LOGO_ZOOM_MIN: Final = 0.5
LOGO_ZOOM_MAX: Final = 3.0
LOGO_FITS: Final = ("circle", "contain")
CONTAIN_BELOW: Final = 0.8
CONTAIN_ABOVE: Final = 1.25


def default_logo_fit(aspect_ratio: float | None) -> str:
    """`contain` for logos that are far from square, else `circle`.

    The ratio is width / height of the stored image; unknown means `circle`.
    """
    if aspect_ratio is None or aspect_ratio <= 0:
        return "circle"
    if aspect_ratio < CONTAIN_BELOW or aspect_ratio > CONTAIN_ABOVE:
        return "contain"
    return "circle"


def resolve_logo_fit(stored: str | None, aspect_ratio: float | None) -> str:
    """A fit set by staff wins; otherwise the aspect-ratio default."""
    return stored if stored in LOGO_FITS else default_logo_fit(aspect_ratio)


def valid_logo_zoom(value: Any) -> bool:
    """Whether the value is a number inside the allowed zoom range."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and LOGO_ZOOM_MIN <= value <= LOGO_ZOOM_MAX
    )


# --- facets -----------------------------------------------------------

COUNTRY_NAMES: Final[Opt] = {
    "US": ("United States", "США", "AQSH"),
    "GB": ("United Kingdom", "Великобритания", "Buyuk Britaniya"),
    "IT": ("Italy", "Италия", "Italiya"),
    "HU": ("Hungary", "Венгрия", "Vengriya"),
    "KR": ("South Korea", "Южная Корея", "Janubiy Koreya"),
    "TR": ("Türkiye", "Турция", "Turkiya"),
    "DE": ("Germany", "Германия", "Germaniya"),
    "JP": ("Japan", "Япония", "Yaponiya"),
    "MY": ("Malaysia", "Малайзия", "Malayziya"),
    "AE": ("United Arab Emirates", "ОАЭ", "BAA"),
    "CA": ("Canada", "Канада", "Kanada"),
    "AU": ("Australia", "Австралия", "Avstraliya"),
    "FR": ("France", "Франция", "Fransiya"),
    "CH": ("Switzerland", "Швейцария", "Shveytsariya"),
    "SG": ("Singapore", "Сингапур", "Singapur"),
    "CN": ("China", "Китай", "Xitoy"),
    "UZ": ("Uzbekistan", "Узбекистан", "Oʻzbekiston"),
}


def country_label(code: str, locale: str = "en") -> str:
    """Localised country name; unknown codes are returned as they are."""
    return option_label(COUNTRY_NAMES, code, locale) if code in COUNTRY_NAMES else code


def _opts(options: Opt, locale: str) -> list[dict[str, str]]:
    return [{"value": v, "label": option_label(options, v, locale)} for v in options]


@dataclass(frozen=True, slots=True)
class FacetInput:
    """What the facet descriptor needs from the catalog."""

    countries: list[str]
    cycles: list[str]
    max_cost: Decimal | None


def facets(data: FacetInput, locale: str = "en") -> list[dict[str, Any]]:
    """Select descriptors {param, label, kind, options} for the filter bar."""
    labels = {
        "country": ("Country", "Страна", "Davlat"),
        "setting": _KEYS["setting"],
        "institution_type": _KEYS["institution_type"],
        "test_policy": _KEYS["test_policy"],
        "aid": _KEYS["aid_basis"],
        "merit_intl": MERIT_INTL,
        "plan": ("Application plan", "План подачи", "Topshirish rejasi"),
        "cycle": ("Cycle", "Цикл", "Sikl"),
        "max_cost": (
            "Max yearly cost, USD",
            "Макс. стоимость в год, USD",
            "Yillik narx, USD",
        ),
    }
    i = _loc(locale)
    cycle_term = CYCLE_TERMS[locale if locale in CYCLE_TERMS else "en"]
    aid = {k: v for k, v in AID_BASIS.items() if k != "need_based"}
    return [
        {
            "param": "country",
            "label": labels["country"][i],
            "kind": "select",
            "options": [
                {"value": c, "label": country_label(c, locale)}
                for c in sorted(data.countries)
            ],
        },
        {
            "param": "setting",
            "label": labels["setting"][i],
            "kind": "select",
            "options": _opts(SETTING, locale),
        },
        {
            "param": "institution_type",
            "label": labels["institution_type"][i],
            "kind": "select",
            "options": _opts(INSTITUTION_TYPE, locale),
        },
        {
            "param": "test_policy",
            "label": labels["test_policy"][i],
            "kind": "select",
            "options": _opts(TEST_POLICY, locale),
        },
        {
            "param": "aid",
            "label": labels["aid"][i],
            "kind": "select",
            "options": _opts(aid, locale),
        },
        {
            "param": "merit_intl",
            "label": labels["merit_intl"][i],
            "kind": "toggle",
            "options": [],
        },
        {
            "param": "plan",
            "label": labels["plan"][i],
            "kind": "select",
            "options": _opts(PLAN, locale),
        },
        {
            "param": "cycle",
            "label": f"{labels['cycle'][i]} ({cycle_term})",
            "kind": "select",
            "options": [{"value": c, "label": c} for c in data.cycles],
        },
        {
            "param": "max_cost",
            "label": labels["max_cost"][i],
            "kind": "number",
            "options": [],
            "max": int(data.max_cost) if data.max_cost is not None else None,
        },
    ]
