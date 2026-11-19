"""Localised view of the international fact registry and of a school's facts."""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from app.modules.admission.domain.catalog_display import (
    AID_BASIS,
    INSTITUTION_TYPE,
    SETTING,
    TEST_POLICY,
    Opt,
    _loc,
    _money,
    _parse_date,
    _rate,
    _short_date,
    option_label,
)
from app.modules.admission.domain.intl_facts import (
    FACT_GROUPS,
    FACT_SPECS,
    IMPORTANCE,
    FactSpec,
)

if TYPE_CHECKING:
    from app.modules.admission.domain.chooser import CatalogInstitution

Labels = tuple[str, str, str]

HIDDEN_KEYS: Final = frozenset({"deadlines", "admission_factors", "fields"})
"""Facts shown elsewhere (deadline list, importance factors, study fields)."""

GROUP_LABELS: Final[dict[str, Labels]] = {
    "overview": ("Overview", "Обзор", "Umumiy maʼlumot"),
    "selectivity": ("Selectivity", "Конкурс и отбор", "Tanlov"),
    "costs": ("Costs and aid", "Стоимость и помощь", "Narx va yordam"),
    "english": ("English", "Английский язык", "Ingliz tili"),
    "credentials": ("Credentials", "Документы об образовании", "Taʼlim hujjatlari"),
    "application": ("Application", "Подача заявки", "Hujjat topshirish"),
    "visa": ("Visa", "Виза", "Viza"),
}
FACT_LABELS: Final[dict[str, Labels]] = {
    "city_type": ("Setting", "Окружение", "Joylashuv"),
    "institution_type": ("Type", "Тип", "Turi"),
    "fields": ("Fields of study", "Направления", "Yoʻnalishlar"),
    "application_platforms": (
        "Application platforms",
        "Платформы подачи",
        "Topshirish platformalari",
    ),
    "mission": ("Mission", "Миссия", "Missiya"),
    "admission_values": (
        "What admissions looks for",
        "Что ценит приёмная комиссия",
        "Qabul komissiyasi nimani qadrlaydi",
    ),
    "acceptance_rate": ("Acceptance rate", "Доля принятых", "Qabul foizi"),
    "intl_acceptance_rate": (
        "International acceptance rate",
        "Доля принятых иностранцев",
        "Xorijliklar qabul foizi",
    ),
    "intl_share": (
        "International students",
        "Доля иностранных студентов",
        "Xorijiy talabalar ulushi",
    ),
    "sat_mid50": ("SAT middle 50%", "SAT, средние 50%", "SAT, oʻrta 50%"),
    "act_mid50": ("ACT middle 50%", "ACT, средние 50%", "ACT, oʻrta 50%"),
    "test_policy": ("Test policy", "Политика тестов", "Testlar siyosati"),
    "admission_factors": (
        "What admissions consider",
        "Что учитывает приёмная комиссия",
        "Qabul komissiyasi nimani hisobga oladi",
    ),
    "intl_tuition_usd": (
        "International tuition",
        "Обучение для иностранцев",
        "Xorijliklar uchun oʻqish narxi",
    ),
    "intl_coa_usd": (
        "Cost of attendance",
        "Полная стоимость обучения",
        "Umumiy xarajatlar",
    ),
    "aid_basis": ("Financial aid", "Финансовая помощь", "Moliyaviy yordam"),
    "meets_full_need": (
        "Meets full need",
        "Покрывает полную нужду",
        "Ehtiyojni toʻliq qoplaydi",
    ),
    "loan_free": ("Loan-free aid", "Помощь без кредитов", "Qarzsiz yordam"),
    "merit_for_internationals": (
        "Merit aid for internationals",
        "Стипендии за достижения для иностранцев",
        "Xorijliklar uchun yutuq stipendiyalari",
    ),
    "aid_application_timing": (
        "When to apply for aid",
        "Когда подавать на помощь",
        "Yordamga qachon topshirish",
    ),
    "aid_forms": ("Aid forms", "Формы для помощи", "Yordam shakllari"),
    "intl_aid_deadline": (
        "International aid deadline",
        "Срок подачи на помощь",
        "Yordam uchun muddat",
    ),
    "application_fee": ("Application fee", "Сбор за подачу", "Topshirish toʻlovi"),
    "fee_waiver": ("Fee waiver", "Освобождение от сбора", "Toʻlovdan ozod qilish"),
    "proof_of_funds": (
        "Proof of funds",
        "Подтверждение средств",
        "Mablagʻni tasdiqlash",
    ),
    "english_tests": (
        "Minimum English scores",
        "Минимальные баллы по английскому",
        "Ingliz tili minimal ballari",
    ),
    "english_waiver": (
        "English waiver",
        "Освобождение от теста",
        "Test talabidan ozod qilish",
    ),
    "ukvi_required": ("UKVI test required", "Нужен тест UKVI", "UKVI testi kerak"),
    "accepted_curricula": (
        "Accepted curricula",
        "Принимаемые программы",
        "Qabul qilinadigan dasturlar",
    ),
    "national_diploma_route": (
        "National diploma",
        "Национальный аттестат",
        "Milliy diplom",
    ),
    "predicted_grades": (
        "Predicted grades",
        "Прогнозные оценки",
        "Taxminiy baholar",
    ),
    "credential_evaluation": (
        "Credential evaluation",
        "Оценка документов",
        "Hujjatlarni baholash",
    ),
    "document_rules": ("Document rules", "Правила для документов", "Hujjat qoidalari"),
    "final_results_before_enrolment": (
        "Final results before enrolment",
        "Итоговые результаты до зачисления",
        "Zachisleniyegacha yakuniy natijalar",
    ),
    "interview": ("Interview", "Собеседование", "Suhbat"),
    "teacher_recommendations": (
        "Teacher recommendations",
        "Рекомендации учителей",
        "Oʻqituvchi tavsiyalari",
    ),
    "counselor_report": (
        "Counselor report",
        "Отчёт консультанта",
        "Maslahatchi hisoboti",
    ),
    "deadlines": ("Deadlines", "Сроки", "Muddatlar"),
    "visa_document": ("Visa document", "Документ для визы", "Viza hujjati"),
}
PART_LABELS: Final[dict[str, Labels]] = {
    "toefl_ibt": ("TOEFL iBT", "TOEFL iBT", "TOEFL iBT"),
    "toefl_new": ("TOEFL (1-6)", "TOEFL (1-6)", "TOEFL (1-6)"),
    "ielts": ("IELTS", "IELTS", "IELTS"),
    "duolingo": ("Duolingo", "Duolingo", "Duolingo"),
    "pte": ("PTE", "PTE", "PTE"),
    "sat_erw": (
        "SAT English",
        "SAT English (чтение и письмо)",
        "SAT ingliz tili (oʻqish va yozish)",
    ),
    "rigor": ("Course rigor", "Сложность программы", "Dastur murakkabligi"),
    "class_rank": ("Class rank", "Место в классе", "Sinfdagi oʻrni"),
    "gpa": ("GPA", "Средний балл", "Oʻrtacha ball"),
    "test_scores": ("Test scores", "Баллы тестов", "Test ballari"),
    "essay": ("Essay", "Эссе", "Insho"),
    "recommendations": ("Recommendations", "Рекомендации", "Tavsiyalar"),
    "interview": ("Interview", "Собеседование", "Suhbat"),
    "extracurricular": (
        "Extracurriculars",
        "Внеучебная деятельность",
        "Darsdan tashqari",
    ),
    "talent": ("Talent", "Талант", "Isteʼdod"),
    "character": ("Character", "Личные качества", "Shaxsiy fazilatlar"),
    "first_generation": (
        "First generation",
        "Первое поколение в вузе",
        "Birinchi avlod",
    ),
    "alumni_relation": (
        "Alumni relation",
        "Связь с выпускниками",
        "Bitiruvchilar bilan aloqa",
    ),
    "geographical_residence": (
        "Geographic residence",
        "Регион проживания",
        "Yashash hududi",
    ),
    "state_residency": ("State residency", "Резидентство штата", "Shtat rezidentligi"),
    "religious": (
        "Religious affiliation",
        "Религиозная принадлежность",
        "Diniy mansublik",
    ),
    "race_ethnic": (
        "Race or ethnicity",
        "Раса или этничность",
        "Irq yoki etnik kelib chiqish",
    ),
    "volunteer": ("Volunteer work", "Волонтёрство", "Ixtiyoriy faoliyat"),
    "work_experience": ("Work experience", "Опыт работы", "Ish tajribasi"),
    "level_of_interest": (
        "Level of interest",
        "Проявленный интерес",
        "Qiziqish darajasi",
    ),
}
IMPORTANCE_LABELS: Final[Opt] = {
    "very_important": ("Very important", "Очень важно", "Juda muhim"),
    "important": ("Important", "Важно", "Muhim"),
    "considered": ("Considered", "Учитывается", "Hisobga olinadi"),
    "not_considered": ("Not considered", "Не учитывается", "Hisobga olinmaydi"),
}
_TIMING: Final[Opt] = {
    "with_application": (
        "With the application",
        "Вместе с заявкой",
        "Ariza bilan birga",
    ),
    "after_admission": ("After admission", "После зачисления", "Qabuldan keyin"),
    "none": ("Not required", "Не требуется", "Talab qilinmaydi"),
}
OPTION_LABELS: Final[dict[str, Opt]] = {
    "city_type": SETTING,
    "institution_type": INSTITUTION_TYPE,
    "test_policy": TEST_POLICY,
    "aid_basis": AID_BASIS,
    "application_platforms": {
        "common_app": ("Common App", "Common App", "Common App"),
        "coalition": ("Coalition App", "Coalition App", "Coalition App"),
        "ucas": ("UCAS", "UCAS", "UCAS"),
        "uc": ("UC application", "Заявка UC", "UC arizasi"),
        "own": ("Own portal", "Собственный портал", "Oʻz portali"),
        "questbridge": ("QuestBridge", "QuestBridge", "QuestBridge"),
        "ouac": ("OUAC", "OUAC", "OUAC"),
    },
    "aid_application_timing": {
        k: _TIMING[k] for k in ("with_application", "after_admission")
    },
    "aid_forms": {
        "css_profile": ("CSS Profile", "CSS Profile", "CSS Profile"),
        "fafsa": ("FAFSA", "FAFSA", "FAFSA"),
        "institutional": (
            "Institutional form",
            "Форма вуза",
            "Universitet shakli",
        ),
        "idoc": ("IDOC", "IDOC", "IDOC"),
    },
    "fee_waiver": {
        "available": ("Available", "Доступно", "Mavjud"),
        "not_available": ("Not available", "Недоступно", "Mavjud emas"),
        "international_eligible": (
            "Available to internationals",
            "Доступно иностранцам",
            "Xorijliklar uchun mavjud",
        ),
    },
    "proof_of_funds": _TIMING,
    "accepted_curricula": {
        "ib": ("IB", "IB", "IB"),
        "a_level": ("A-level", "A-level", "A-level"),
        "ap": ("AP", "AP", "AP"),
        "national": ("National diploma", "Национальный аттестат", "Milliy diplom"),
    },
    "national_diploma_route": {
        "direct": ("Accepted directly", "Принимается напрямую", "Toʻgʻridan-toʻgʻri"),
        "foundation_year": (
            "Foundation year",
            "Подготовительный год",
            "Tayyorlov yili",
        ),
        "not_accepted": ("Not accepted", "Не принимается", "Qabul qilinmaydi"),
    },
    "credential_evaluation": {
        "not_required": ("Not required", "Не требуется", "Talab qilinmaydi"),
        "wes": ("WES", "WES", "WES"),
        "ece": ("ECE", "ECE", "ECE"),
        "naces_any": ("Any NACES member", "Любой член NACES", "Istalgan NACES aʼzosi"),
    },
    "document_rules": {
        "certified_translation": (
            "Certified translation",
            "Заверенный перевод",
            "Tasdiqlangan tarjima",
        ),
        "notarisation": ("Notarisation", "Нотариальное заверение", "Notarial tasdiq"),
        "apostille": ("Apostille", "Апостиль", "Apostil"),
    },
    "interview": {
        "none": ("No interview", "Без собеседования", "Suhbatsiz"),
        "optional": ("Optional", "По желанию", "Ixtiyoriy"),
        "recommended": ("Recommended", "Рекомендуется", "Tavsiya etiladi"),
        "required": ("Required", "Обязательно", "Majburiy"),
        "third_party": (
            "Third-party interview",
            "Внешнее собеседование",
            "Tashqi suhbat",
        ),
    },
    "visa_document": {
        "i20": ("Form I-20", "Форма I-20", "I-20 shakli"),
        "ds2019": ("Form DS-2019", "Форма DS-2019", "DS-2019 shakli"),
        "cas": ("CAS", "CAS", "CAS"),
        "other": ("Other", "Другое", "Boshqa"),
    },
}
_YES: Final = ("Yes", "Да", "Ha")
_NO: Final = ("No", "Нет", "Yoʻq")


def _options(spec: FactSpec) -> Opt:
    """Labels of the spec's options (importance for factors)."""
    if spec.kind == "factors":
        return IMPORTANCE_LABELS
    return OPTION_LABELS.get(spec.key, {})


def _label(table: dict[str, Labels], key: str, locale: str) -> str:
    labels = table.get(key)
    return labels[_loc(locale)] if labels else key.replace("_", " ").capitalize()


_SHAPES: Final[dict[str, str]] = {
    "bool": "true or false",
    "int": "a whole number within min..max",
    "percent": "a number within min..max (0-100)",
    "money": '{"amount": number >= 0, "currency": ISO-4217 code, e.g. "USD"}',
    "date": 'a calendar date "YYYY-MM-DD"',
    "text": "plain text, at most 300 characters",
    "enum": "exactly one of the option values",
    "multi": "a non-empty list of distinct option values",
    "range": '{"min": number, "max": number} within min..max, min <= max; '
    "a single number means min = max",
    "scores": "an object of part keys with a number each, within each part's range",
    "factors": "an object of part keys, each set to one of the option values",
    "deadlines": '[{"plan": ED|ED2|EA|REA|SCEA|RD|ROLLING|OTHER, "date": '
    '"YYYY-MM-DD", "cycle": "YYYY-YY", "binding"?: bool, "time_zone"?: IANA zone, '
    '"note"?: text <= 200}], at most 12',
    "study_fields": "a list of 1-40 field-of-study names or canonical ids",
}


def _example(spec: FactSpec) -> Any:
    """A valid sample value of the fact, for the staff form and API agents."""
    first = spec.options[0] if spec.options else None
    low = spec.min if spec.min is not None else 0
    high = spec.max if spec.max is not None else low + 1
    part = spec.parts[0] if spec.parts else None
    examples: dict[str, Any] = {
        "bool": True,
        "int": int(low),
        "percent": low,
        "money": {"amount": 52000, "currency": spec.unit or "USD"},
        "date": "2026-01-15",
        "text": "One or two plain sentences.",
        "enum": first,
        "multi": [first],
        "range": {"min": low, "max": high},
        "scores": {part.key: part.max or 1} if part else {},
        "factors": {part.key: first} if part else {},
        "deadlines": [{"plan": "RD", "date": "2027-01-05", "cycle": "2026-27"}],
        "study_fields": ["Computer science"],
    }
    return examples[spec.kind]


def fact_spec_view(locale: str = "en") -> list[dict[str, Any]]:
    """Registry for the staff form: groups with facts, labels in the locale."""
    groups: list[dict[str, Any]] = []
    for group in FACT_GROUPS:
        facts: list[dict[str, Any]] = []
        for spec in FACT_SPECS.values():
            if spec.group != group:
                continue
            labels = _options(spec)
            facts.append(
                {
                    "key": spec.key,
                    "label": _label(FACT_LABELS, spec.key, locale),
                    "kind": spec.kind,
                    "options": [
                        {"value": o, "label": option_label(labels, o, locale)}
                        for o in spec.options
                    ],
                    "parts": [
                        {
                            "key": p.key,
                            "label": _label(PART_LABELS, p.key, locale),
                            "min": p.min,
                            "max": p.max,
                            "step": p.step,
                        }
                        for p in spec.parts
                    ],
                    "min": spec.min,
                    "max": spec.max,
                    "step": spec.step,
                    "unit": spec.unit,
                    "value_shape": _SHAPES[spec.kind],
                    "example": _example(spec),
                }
            )
        groups.append(
            {
                "key": group,
                "label": _label(GROUP_LABELS, group, locale),
                "facts": facts,
            }
        )
    return groups


def _json(v: Any) -> Any:
    """JSON-safe copy of a stored value."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def _g(v: float | int) -> str:
    return f"{v:g}"


def _range_text(v: Any, unit: str | None) -> str | None:
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        v = {"min": v, "max": v}
    if unit == "percent":
        return _rate(v)
    if not isinstance(v, dict):
        return None
    lo: Any = v.get("min")
    hi: Any = v.get("max")
    if lo is None and hi is None:
        return None
    lo, hi = (hi if lo is None else lo), (lo if hi is None else hi)
    return _g(lo) if lo == hi else f"{_g(lo)}-{_g(hi)}"


def _text_bool(spec: FactSpec, value: Any, unit: str | None, locale: str) -> str:
    return (_YES if value else _NO)[_loc(locale)]


def _text_plain(spec: FactSpec, value: Any, unit: str | None, locale: str) -> str:
    return str(value)


def _text_percent(
    spec: FactSpec, value: Any, unit: str | None, locale: str
) -> str | None:
    return f"{_g(float(value))}%" if isinstance(value, (int, float)) else None


def _text_money(
    spec: FactSpec, value: Any, unit: str | None, locale: str
) -> str | None:
    if not isinstance(value, (int, float, str, Decimal)):
        return None
    return _money(value, unit or spec.unit or "USD")


def _text_date(spec: FactSpec, value: Any, unit: str | None, locale: str) -> str:
    d = _parse_date(value)
    return f"{_short_date(d, locale)} {d.year}" if d else str(value)


def _text_enum(spec: FactSpec, value: Any, unit: str | None, locale: str) -> str:
    return option_label(_options(spec), str(value), locale)


def _text_multi(
    spec: FactSpec, value: Any, unit: str | None, locale: str
) -> str | None:
    if not isinstance(value, list):
        return None
    labels = _options(spec)
    return ", ".join(option_label(labels, str(x), locale) for x in value)


def _text_range(
    spec: FactSpec, value: Any, unit: str | None, locale: str
) -> str | None:
    return _range_text(value, unit or spec.unit)


def _text_scores(
    spec: FactSpec, value: Any, unit: str | None, locale: str
) -> str | None:
    if not isinstance(value, dict):
        return None
    return " · ".join(
        f"{_label(PART_LABELS, p.key, locale)} {_g(value[p.key])}"
        for p in spec.parts
        if isinstance(value.get(p.key), (int, float))
    )


_TEXTERS: Final[dict[str, Callable[[FactSpec, Any, str | None, str], str | None]]] = {
    "bool": _text_bool,
    "int": _text_plain,
    "text": _text_plain,
    "percent": _text_percent,
    "money": _text_money,
    "date": _text_date,
    "enum": _text_enum,
    "multi": _text_multi,
    "range": _text_range,
    "scores": _text_scores,
}


def _value_text(
    spec: FactSpec, value: Any, unit: str | None, locale: str
) -> str | None:
    texter = _TEXTERS.get(spec.kind)
    return texter(spec, value, unit, locale) if texter else None


def detail_groups(
    inst: "CatalogInstitution", locale: str = "en"
) -> list[dict[str, Any]]:
    """Facts of the school by group; only facts with a value, no notes."""
    out: list[dict[str, Any]] = []
    for group in FACT_GROUPS:
        rows: list[dict[str, Any]] = []
        for spec in FACT_SPECS.values():
            if spec.group != group or spec.key in HIDDEN_KEYS:
                continue
            fact = inst.fact(spec.key)
            if fact is None:
                continue
            text = _value_text(spec, fact.value, fact.unit, locale)
            if not text:
                continue
            rows.append(
                {
                    "key": spec.key,
                    "label": _label(FACT_LABELS, spec.key, locale),
                    "kind": spec.kind,
                    "value": _json(fact.value),
                    "value_text": text,
                    "source_url": fact.source_url,
                    "year": fact.year,
                }
            )
        if rows:
            out.append(
                {
                    "key": group,
                    "label": _label(GROUP_LABELS, group, locale),
                    "rows": rows,
                }
            )
    return out


def importance_factors(
    inst: "CatalogInstitution", locale: str = "en"
) -> list[dict[str, str]]:
    """`[{key, label, importance}]` of the admission factors in registry order."""
    fact = inst.fact("admission_factors")
    if fact is None or not isinstance(fact.value, dict):
        return []
    out: list[dict[str, str]] = []
    for part in FACT_SPECS["admission_factors"].parts:
        level = fact.value.get(part.key)
        if level in IMPORTANCE:
            out.append(
                {
                    "key": part.key,
                    "label": _label(PART_LABELS, part.key, locale),
                    "importance": level,
                }
            )
    return out
