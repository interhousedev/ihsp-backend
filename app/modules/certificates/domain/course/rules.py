"""Course certificate rules: tiers, template layout, partners and evaluation.

Positions and sizes of a layout are fractions of the page (0..1), so the web
constructor and the server renderer agree whatever the background size.
"""

import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from app.modules.certificates.domain.errors import CourseCertificateInvalidError

LOCALES: Final = ("en", "ru", "uz")
FONTS: Final = {
    "montserrat": "Montserrat-Variable.ttf",
    "oswald": "Oswald-Variable.ttf",
    "lora": "Lora-Variable.ttf",
    "eb_garamond": "EBGaramond-Variable.ttf",
    "cormorant": "CormorantGaramond-Variable.ttf",
}
FIELD_KEYS: Final = frozenset(
    {"name", "course", "tier", "date", "partner", "code", "qr", "custom_text"}
)
ALIGNS: Final = frozenset({"left", "center", "right"})
QR_STYLES: Final = frozenset({"square", "rounded", "dots"})
MAX_TIERS: Final = 8
MAX_FIELDS: Final = 24
CODE_ALPHABET: Final = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH: Final = 12
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _bad(name: str) -> CourseCertificateInvalidError:
    return CourseCertificateInvalidError(params={"field": name})


def _text(
    raw: Any, name: str, limit: int, *, required: bool = True
) -> str:  # noqa: ANN401
    value = str(raw or "").strip()
    if (required and not value) or len(value) > limit:
        raise _bad(name)
    return value


def _fraction(
    raw: Any, name: str, low: float = 0.0, high: float = 1.0
) -> float:  # noqa: ANN401
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _bad(name) from None
    if not low <= value <= high:
        raise _bad(name)
    return round(value, 5)


def color(raw: Any, name: str) -> str:  # noqa: ANN401
    """Return a ``#rrggbb`` colour in lower case or raise."""
    value = str(raw or "")
    if not _COLOR.match(value):
        raise _bad(name)
    return value.lower()


def new_code() -> str:
    """Return a random verification code (60 bits, no look-alike letters)."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


@dataclass(frozen=True, slots=True)
class Tier:
    """A finishing level: Normal, With honours, Extra ...; ordered low to high."""

    key: str
    label: dict[str, str]
    min_pct: int | None = None
    require_optional: bool = False
    color: str = "#1f2937"

    def to_dict(self) -> dict[str, Any]:
        """Return the stored form."""
        return {
            "key": self.key,
            "label": dict(self.label),
            "min_pct": self.min_pct,
            "require_optional": self.require_optional,
            "color": self.color,
        }


def parse_tiers(raw: Sequence[Mapping[str, Any]]) -> tuple[Tier, ...]:
    """Validate the tier list (1 to 8 tiers, unique keys, labels in every locale)."""
    if not 1 <= len(raw) <= MAX_TIERS:
        raise _bad("tiers")
    tiers: list[Tier] = []
    for index, item in enumerate(raw):
        key = str(item.get("key", ""))
        if not _KEY.match(key) or any(t.key == key for t in tiers):
            raise _bad(f"tiers.{index}.key")
        labels = item.get("label") or {}
        label = {
            loc: _text(labels.get(loc), f"tiers.{index}.label.{loc}", 60)
            for loc in LOCALES
        }
        min_pct = item.get("min_pct")
        if min_pct is not None:
            min_pct = int(_fraction(min_pct, f"tiers.{index}.min_pct", 0, 100))
        tiers.append(
            Tier(
                key=key,
                label=label,
                min_pct=min_pct,
                require_optional=bool(item.get("require_optional", False)),
                color=color(item.get("color") or "#1f2937", f"tiers.{index}.color"),
            )
        )
    return tuple(tiers)


def default_tiers() -> tuple[Tier, ...]:
    """Normal, With honours (90 %) and Extra (honours plus every optional section)."""
    return (
        Tier(
            "normal", {"en": "Completed", "ru": "Курс пройден", "uz": "Kurs tugallandi"}
        ),
        Tier(
            "honors",
            {"en": "With honours", "ru": "С отличием", "uz": "Imtiyozli"},
            min_pct=90,
            color="#b45309",
        ),
        Tier(
            "extra",
            {
                "en": "With distinction",
                "ru": "С особым отличием",
                "uz": "Alohida imtiyozli",
            },
            min_pct=90,
            require_optional=True,
            color="#7c3aed",
        ),
    )


@dataclass(slots=True)
class CertificateSettings:
    """The certificate settings of one course."""

    course_id: UUID
    enabled: bool = False
    passing_pct: int = 60
    optional_section_ids: tuple[str, ...] = ()
    tiers: tuple[Tier, ...] = field(default_factory=default_tiers)
    template_id: UUID | None = None
    partner_ids: tuple[UUID, ...] = ()


def apply_settings(
    current: CertificateSettings, raw: Mapping[str, Any]
) -> CertificateSettings:
    """Return validated settings from the request body."""
    optional = raw.get("optional_section_ids") or []
    if len(optional) > 200:
        raise _bad("optional_section_ids")
    partners = raw.get("partner_ids") or []
    template = raw.get("template_id")
    return CertificateSettings(
        course_id=current.course_id,
        enabled=bool(raw.get("enabled", False)),
        passing_pct=int(_fraction(raw.get("passing_pct", 0), "passing_pct", 0, 100)),
        optional_section_ids=tuple(
            _text(s, "optional_section_ids", 64) for s in optional
        ),
        tiers=parse_tiers(raw.get("tiers") or []),
        template_id=UUID(str(template)) if template else None,
        partner_ids=tuple(UUID(str(p)) for p in partners[:10]),
    )


@dataclass(frozen=True, slots=True)
class SectionResult:
    """What a learner did in one section of the live course."""

    section_id: str
    steps_total: int
    steps_done: int
    points_total: Decimal
    points_earned: Decimal


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Where a learner stands: score, whether they passed and the tier earned."""

    score_pct: int
    required_done: bool
    optional_done: bool
    passed: bool
    tier: Tier | None
    next_tier: Tier | None
    required_steps_left: int = 0


def evaluate(
    settings: CertificateSettings, sections: Sequence[SectionResult]
) -> Evaluation:
    """Evaluate the tiers: the highest tier whose conditions hold wins.

    The score counts required sections only (optional work never lowers it). A
    learner passes with every required step done and the score at the passing
    mark; a tier without ``min_pct`` uses the passing mark.
    """
    optional_ids = set(settings.optional_section_ids)
    required = [s for s in sections if s.section_id not in optional_ids]
    optional = [s for s in sections if s.section_id in optional_ids]
    total = sum((s.points_total for s in required), Decimal(0))
    earned = sum((s.points_earned for s in required), Decimal(0))
    score = 100 if total <= 0 else int((earned * 100 / total).to_integral_value())
    score = max(0, min(100, score))
    required_done = all(s.steps_done >= s.steps_total for s in required)
    optional_done = all(s.steps_done >= s.steps_total for s in optional)
    passed = required_done and score >= settings.passing_pct
    tier: Tier | None = None
    for candidate in settings.tiers:
        threshold = max(candidate.min_pct or 0, settings.passing_pct)
        if (
            passed
            and score >= threshold
            and (optional_done or not candidate.require_optional)
        ):
            tier = candidate
    if passed and tier is None:
        tier = settings.tiers[0]
    order = list(settings.tiers)
    after = order.index(tier) + 1 if tier is not None else 0
    next_tier = order[after] if after < len(order) else None
    steps_left = sum(max(0, s.steps_total - s.steps_done) for s in required)
    return Evaluation(
        score, required_done, optional_done, passed, tier, next_tier, steps_left
    )


def tier_rank(settings: CertificateSettings, key: str) -> int:
    """Return the position of a tier (-1 when it was removed)."""
    keys = [t.key for t in settings.tiers]
    return keys.index(key) if key in keys else -1


def parse_fields(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate the placed fields of a template layout."""
    if len(raw) > MAX_FIELDS:
        raise _bad("fields")
    fields: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        name = f"fields.{index}"
        key = str(item.get("key", ""))
        if key not in FIELD_KEYS:
            raise _bad(f"{name}.key")
        font = str(item.get("font") or "montserrat")
        if font not in FONTS:
            raise _bad(f"{name}.font")
        align = str(item.get("align") or "center")
        if align not in ALIGNS:
            raise _bad(f"{name}.align")
        weight = int(_fraction(item.get("weight", 400), f"{name}.weight", 100, 900))
        text = item.get("text")
        fields.append(
            {
                "key": key,
                "x": _fraction(item.get("x"), f"{name}.x"),
                "y": _fraction(item.get("y"), f"{name}.y"),
                "w": _fraction(item.get("w"), f"{name}.w", 0.01),
                "h": _fraction(item.get("h"), f"{name}.h", 0.01),
                "font": font,
                "size": _fraction(item.get("size", 0.05), f"{name}.size", 0.005, 0.5),
                "weight": weight,
                "color": color(item.get("color") or "#111111", f"{name}.color"),
                "align": align,
                "text": (
                    _text(text, f"{name}.text", 200, required=False)
                    if key == "custom_text"
                    else None
                ),
            }
        )
    return fields


def parse_qr(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate the QR style."""
    raw = raw or {}
    style = str(raw.get("style") or "square")
    if style not in QR_STYLES:
        raise _bad("qr.style")
    return {
        "fg": color(raw.get("fg") or "#000000", "qr.fg"),
        "bg": color(raw.get("bg") or "#ffffff", "qr.bg"),
        "style": style,
        "logo": bool(raw.get("logo", False)),
    }


def default_fields() -> list[dict[str, Any]]:
    """A starting layout: name, course, tier, date, code and the QR."""
    base = {"font": "lora", "weight": 400, "color": "#111111", "text": None}
    return [
        {
            **base,
            "key": "name",
            "x": 0.1,
            "y": 0.38,
            "w": 0.8,
            "h": 0.1,
            "size": 0.08,
            "align": "center",
            "weight": 700,
        },  # noqa: E501
        {
            **base,
            "key": "course",
            "x": 0.1,
            "y": 0.52,
            "w": 0.8,
            "h": 0.07,
            "size": 0.045,
            "align": "center",
        },  # noqa: E501
        {
            **base,
            "key": "tier",
            "x": 0.1,
            "y": 0.6,
            "w": 0.8,
            "h": 0.06,
            "size": 0.04,
            "align": "center",
        },  # noqa: E501
        {
            **base,
            "key": "date",
            "x": 0.08,
            "y": 0.82,
            "w": 0.3,
            "h": 0.05,
            "size": 0.03,
            "align": "left",
        },  # noqa: E501
        {
            **base,
            "key": "code",
            "x": 0.08,
            "y": 0.88,
            "w": 0.3,
            "h": 0.04,
            "size": 0.025,
            "align": "left",
            "font": "montserrat",
        },  # noqa: E501
        {
            **base,
            "key": "qr",
            "x": 0.8,
            "y": 0.75,
            "w": 0.13,
            "h": 0.18,
            "size": 0.05,
            "align": "center",
        },  # noqa: E501
    ]


def partner_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a partner: name, https/http URL, co-issued flag."""
    url = _text(raw.get("url"), "url", 500, required=False)
    if url and not re.match(r"^https?://[^\s/]+\.[^\s]+$", url):
        raise _bad("url")
    return {
        "name": _text(raw.get("name"), "name", 160),
        "url": url or None,
        "co_issued": bool(raw.get("co_issued", True)),
    }
