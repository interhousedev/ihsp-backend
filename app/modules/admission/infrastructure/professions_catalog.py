"""The professions snapshot (`professions_data/professions.json`) as a catalogue."""

import json
from functools import cache
from pathlib import Path

from app.modules.admission.domain.professions import (
    MAJOR_GROUPS,
    Profession,
    Source,
)

_FILE = Path(__file__).parent / "professions_data" / "professions.json"


@cache
def _load() -> tuple[Profession, ...]:
    data = json.loads(_FILE.read_text("utf-8"))
    cited = tuple(
        Source(s["label"], s["url"])
        for k in ("exposure", "names_en")
        if (s := data["sources"].get(k))
    )
    return tuple(
        Profession(
            id=i["id"],
            group=i["group"],
            names=i["name"],
            ai_exposure=i["ai_exposure"],
            ai_risk=i["ai_risk"],
            horizon=i["horizon"],
            related_fields=tuple(i["related_fields"]),
            salary_band=i.get("salary_band"),
            sources=cited,
        )
        for i in sorted(data["items"], key=lambda x: x["id"])
        if i["group"] in MAJOR_GROUPS
    )


class JsonProfessionCatalog:
    """Read-only catalogue of the snapshot."""

    def all(self) -> tuple[Profession, ...]:
        """Every profession, in id order."""
        return _load()

    def get(self, profession_id: str) -> Profession | None:
        """One profession by ISCO code."""
        return _index().get(profession_id)


@cache
def _index() -> dict[str, Profession]:
    return {p.id: p for p in _load()}
