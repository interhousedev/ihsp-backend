"""Seed loader: deterministic ids make a second load rewrite the same rows."""

from typing import Any

from app.modules.admission.infrastructure.catalog_loader import load_catalog
from app.modules.admission.infrastructure.orm.catalog import FactRow, InstitutionRow
from tests.admission.unit.fakes import NOW


class _Session:
    def __init__(self) -> None:
        self.rows: dict[tuple[type, Any], Any] = {}

    async def merge(self, obj: Any) -> Any:
        self.rows[(type(obj), obj.id)] = obj
        return obj

    async def flush(self) -> None:
        return None


async def test_load_is_idempotent_and_marks_verification() -> None:
    s = _Session()
    first = await load_catalog(s, NOW)  # type: ignore[arg-type]
    count = len(s.rows)
    second = await load_catalog(s, NOW)  # type: ignore[arg-type]
    assert first == second and len(s.rows) == count and first.institutions > 0
    insts = [o for (t, _), o in s.rows.items() if t is InstitutionRow]
    assert {i.status for i in insts} <= {"published", "provisional"}
    facts = [o for (t, _), o in s.rows.items() if t is FactRow]
    assert all(f.value is not None for f in facts)
    assert {f.confidence for f in facts} <= {"official", "manual"}
