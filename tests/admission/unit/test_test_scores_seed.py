"""The migration's seeded catalog is a valid set of definitions."""

import importlib.util
from pathlib import Path

from app.modules.admission.domain.test_scores import ScoreTest, validate_definition
from app.modules.admission.infrastructure.test_scores_repository import section_from
from app.shared.ids import new_id

PATH = Path("migrations/versions/admission/admission_0016_test_scores.py")


def _seed() -> tuple[dict, ...]:
    spec = importlib.util.spec_from_file_location("m0016", PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "admission_0016_test_scores"
    assert mod.down_revision == "admission_0015_items_status"
    return mod.SEED


def test_seed_is_valid_and_complete() -> None:
    seed = _seed()
    keys = {r["key"] for r in seed}
    assert {"sat", "act", "ielts_academic", "toefl_ibt", "duolingo", "ap"} <= keys
    assert {"ib_diploma", "a_level", "cambridge_c1", "cambridge_c2", "olympiad"} <= keys
    for r in seed:
        validate_definition(
            ScoreTest(
                id=new_id(),
                key=r["key"],
                names=r["names"],
                sections=tuple(section_from(s) for s in r["sections"]),
                total=section_from(r["total"]) if r["total"] else None,
                total_mode=r["total_mode"],
                superscore=r["superscore"],
                needs_label=r["needs_label"],
                needs_level=r["needs_level"],
                position=r["position"],
            )
        )
