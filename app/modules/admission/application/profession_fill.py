"""Turn the model's card of a typed-in profession into a custom `Profession`."""

from typing import Any
from uuid import uuid4

from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import plain
from app.modules.admission.domain.professions import (
    CUSTOM_ID_PREFIX,
    LANGS,
    MAJOR_GROUPS,
    SCORE_MAX,
    Profession,
    horizon_of,
    risk_of,
)
from app.modules.admission.ports.fit import ProfessionCatalog

NAME_MAX = 120
DESCRIPTION_MAX = 400
FIELDS_MAX = 6
_BANDS = ("low", "medium", "high")


def _text(value: Any, limit: int) -> str:
    return nfc(plain(str(value or ""))).strip()[:limit]


def field_vocabulary(catalog: ProfessionCatalog) -> list[str]:
    """Every field of study the catalogue links professions to, sorted."""
    return sorted({f for p in catalog.all() for f in p.related_fields})


def _closest(isco: str, catalog: ProfessionCatalog) -> Profession | None:
    """The catalogue entry of the code, else the first one of its 3-digit unit."""
    if (hit := catalog.get(isco)) is not None:
        return hit
    if len(isco) == 4 and isco.isdigit():
        return next((p for p in catalog.all() if p.id[:3] == isco[:3]), None)
    return None


def build_custom(
    data: dict[str, Any], title: str, catalog: ProfessionCatalog
) -> Profession:
    """Build a new custom profession.

    The typed title is the name in every language the model left empty. Exposure
    comes from the matching ISCO entry when there is one, else from the model's
    clamped estimate.
    """
    names = {lang: _text(data.get(f"name_{lang}"), NAME_MAX) or title for lang in LANGS}
    descriptions = {
        lang: d
        for lang in LANGS
        if (d := _text(data.get(f"description_{lang}"), DESCRIPTION_MAX))
    }
    isco = _text(data.get("isco_id"), 4)
    near = _closest(isco, catalog)
    known = set(field_vocabulary(catalog))
    raw = data.get("related_fields")
    fields = [str(f).strip().lower() for f in raw] if isinstance(raw, list) else []
    related = tuple(dict.fromkeys(f for f in fields if f in known))[:FIELDS_MAX]
    if not related and near is not None:
        related = near.related_fields
    if near is not None:
        score, band = near.ai_exposure, near.salary_band
        group = near.group
    else:
        try:
            score = min(max(float(data.get("ai_exposure", 0.0)), 0.0), SCORE_MAX)
        except (TypeError, ValueError):
            score = 0.0
        raw_band = _text(data.get("salary_band"), 10)
        band = raw_band if raw_band in _BANDS else None  # type: ignore[assignment]
        group = isco[:1] if isco[:1] in MAJOR_GROUPS else "2"
    return Profession(
        id=f"{CUSTOM_ID_PREFIX}{uuid4().hex[:12]}",
        group=group,
        names=names,
        ai_exposure=score,
        ai_risk=risk_of(score),
        horizon=horizon_of(score, ""),
        related_fields=related,
        salary_band=band,
        descriptions=descriptions,
        custom=True,
        isco_id=near.id if near is not None else None,
    )
