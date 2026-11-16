"""Items slice: rubric, schemas and `items_summary` (pure, no I/O)."""

import datetime as dt
import json
from decimal import Decimal
from typing import Any

from app.modules.admission.application.items import items_summary
from app.modules.admission.application.review_rubric import (
    DIMENSIONS,
    PROJECTED_IMPACT_CAP,
    cap,
    overall_item,
    rubric_text,
)
from app.modules.admission.application.review_schema import (
    INTERVIEW_SCHEMA,
    REVIEW_SCHEMA,
    REWRITE_SCHEMA,
)
from app.modules.admission.domain.items import Item
from app.modules.admission.ports.items import Metric
from app.shared.ids import new_id

import pytest


def _unions(node: Any) -> int:
    if isinstance(node, dict):
        own = sum(1 for k in ("anyOf", "oneOf") if k in node)
        if isinstance(node.get("type"), list):
            own += 1
        return own + sum(_unions(v) for v in node.values())
    if isinstance(node, list):
        return sum(_unions(v) for v in node)
    return 0


@pytest.mark.parametrize("schema", [REVIEW_SCHEMA, INTERVIEW_SCHEMA, REWRITE_SCHEMA])
def test_schemas_are_strict_without_unions(schema: dict[str, Any]) -> None:
    assert _unions(schema) == 0
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "$ref" not in json.dumps(schema) or "$defs" in schema


def test_overall_and_caps() -> None:
    assert overall_item(dict.fromkeys(DIMENSIONS, "A")) == "A"
    grades = dict.fromkeys(DIMENSIONS, "A") | {"impact": "E"}
    assert overall_item(grades) in ("D", "E")
    assert cap("A", PROJECTED_IMPACT_CAP) == "C"
    assert cap("D", PROJECTED_IMPACT_CAP) == "D"
    assert "impact" in rubric_text("activity")


def test_items_summary_marks_plans() -> None:
    student = new_id()
    a = Item(new_id(), student, "activity", "Captain", "Robotics club", position=1)
    h = Item(new_id(), student, "honor", "Olympiad", position=0)
    metrics = {
        a.id: [
            Metric(new_id(), a.id, "Members", Decimal("20"), "people", "current"),
            Metric(
                new_id(),
                a.id,
                "Members",
                Decimal("40.0"),
                None,
                "projected",
                target_date=dt.date(2027, 5, 1),
            ),
        ]
    }
    out = items_summary([h, a], metrics)
    assert [o["kind"] for o in out] == ["activity", "honor"]
    assert out[0]["metrics"] == [
        "Members: 20 people",
        "Members: 40 (planned by 2027-05-01)",
    ]
    assert out[1]["metrics"] == []


def test_golden_set_is_complete() -> None:
    from scripts.admission_eval import load_cases

    cases = load_cases()
    assert len(cases) >= 30
    assert {c.locale for c in cases} == {"uz", "ru", "en"}
    assert {c.data.item.kind for c in cases} == {"activity", "honor"}
    assert all(set(c.expected) == set(DIMENSIONS) for c in cases)
