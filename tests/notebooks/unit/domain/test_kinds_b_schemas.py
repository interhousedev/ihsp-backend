"""NB-14: strict JSON schemas of quiz, data table, slides and infographic (§ 6.3)."""

import json
from typing import Any

from app.modules.notebooks.domain.artifacts.handler import (
    ArtifactHandler,
    ProcessContext,
)
from app.modules.notebooks.domain.artifacts.kinds import (
    data_table,
    infographic,
    quiz,
    slides,
)
from app.modules.notebooks.domain.artifacts.registry import (
    handler_for,
    supported_kinds,
)
from app.modules.notebooks.domain.artifacts.strict import (
    MAX_UNION_PARAMETERS,
    count_unions,
)
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.prompts.slides_revise import revise_schema
from tests.notebooks.unit.domain.kinds_b_pack import two_source_pack

import pytest

HANDLERS: dict[str, ArtifactHandler] = {
    "quiz": quiz.HANDLER,
    "data_table": data_table.HANDLER,
    "slides": slides.HANDLER,
    "infographic": infographic.HANDLER,
}
CTX = ProcessContext(pack=two_source_pack(), language="en", seed=3)
FORBIDDEN_KEYWORDS = {
    "$ref",
    "$defs",
    "default",
    "title",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "pattern",
    "format",
    "x-not-null",
}

# One complete document per kind in the shape the strict schema asks for: every
# property present, optional ones null.
SAMPLES: dict[str, dict[str, Any]] = {
    "quiz": {
        "title": "Photosynthesis: quiz",
        "questions": [
            {
                "id": "q1",
                "type": "single",
                "prompt": "Which gas is released in the light reactions?",
                "options": [
                    {"id": "a", "text": "Oxygen"},
                    {"id": "b", "text": "Carbon dioxide"},
                    {"id": "c", "text": "Nitrogen"},
                    {"id": "d", "text": "Hydrogen"},
                ],
                "correct": ["a"],
                "explanation": "Water is split and oxygen is released.",
                "hint": "Water is split.",
                "difficulty": "easy",
                "topic": "Light reactions",
                "refs": ["S1:P3"],
            },
            {
                "id": "q2",
                "type": "true_false",
                "prompt": "The Calvin cycle needs light directly.",
                "options": [
                    {"id": "true", "text": "True"},
                    {"id": "false", "text": "False"},
                ],
                "correct": ["false"],
                "explanation": "It uses ATP and NADPH made in the light reactions.",
                "hint": None,
                "difficulty": None,
                "topic": None,
                "refs": ["S1:P2"],
            },
        ],
    },
    "data_table": {
        "title": "Events",
        "columns": [
            {"key": "year", "label": "Year", "type": "number"},
            {"key": "event", "label": "Event", "type": "text"},
        ],
        "rows": [
            {
                "cells": [
                    {"key": "year", "value": "1873"},
                    {"key": "event", "value": "Protectorate"},
                ],
                "refs": ["S2:P1"],
            }
        ],
    },
    "slides": {
        "title": "Photosynthesis",
        "subtitle": None,
        "slides": [
            {
                "id": "s1",
                "layout": "title",
                "title": "Photosynthesis",
                "bullets": [],
                "body": None,
                "left": None,
                "right": None,
                "quote": None,
                "table": None,
                "notes": "Welcome",
                "visual_hint": None,
                "refs": [],
            },
            {
                "id": "s2",
                "layout": "table",
                "title": "Stages",
                "bullets": None,
                "body": None,
                "left": None,
                "right": None,
                "quote": None,
                "table": {
                    "columns": ["Stage", "Where"],
                    "rows": [["Light", "Thylakoid"]],
                },
                "notes": "",
                "visual_hint": "Two-box diagram",
                "refs": ["S1:P2"],
            },
            {
                "id": "s3",
                "layout": "summary",
                "title": "Summary",
                "bullets": ["Plants make glucose"],
                "body": None,
                "left": None,
                "right": None,
                "quote": None,
                "table": None,
                "notes": "Recap",
                "visual_hint": None,
                "refs": ["S1:P1"],
            },
        ],
    },
    "infographic": {
        "title": "Photosynthesis at a glance",
        "subtitle": None,
        "footer": "Source: Lesson 5",
        "blocks": [
            {
                "type": "stat",
                "title": "",
                "items": [{"head": "6CO2 + 6H2O", "body": "→ C6H12O6 + 6O2"}],
                "columns": None,
                "refs": ["S1:P2"],
            },
            {
                "type": "list",
                "title": "Parts",
                "items": [{"head": "Leaf", "body": "Absorbs light"}],
                "columns": None,
                "refs": ["S1:P1"],
            },
            {
                "type": "comparison",
                "title": "Two stages",
                "items": [],
                "columns": [
                    {"title": "Light", "points": ["a"]},
                    {"title": "Calvin", "points": ["b"]},
                ],
                "refs": ["S1:P3"],
            },
        ],
    },
}


def walk(node: Any) -> list[dict[str, Any]]:
    """Every schema object (dict) in the tree."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(walk(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(walk(value))
    return found


@pytest.mark.parametrize("name", HANDLERS)
def test_strict_schema_is_a_closed_object_at_every_level(name: str) -> None:
    """NB-14: additionalProperties false and all properties required, everywhere."""
    schema = HANDLERS[name].strict_schema()

    assert schema["type"] == "object"
    objects = [n for n in walk(schema) if n.get("type") == "object"]
    assert len(objects) >= 2
    for node in objects:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


@pytest.mark.parametrize("name", HANDLERS)
def keywords(node: Any) -> set[str]:
    """Schema keywords used in the tree (property names are not keywords)."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties":
                for sub in value.values():
                    found |= keywords(sub)
            else:
                found.add(key)
                found |= keywords(value)
    elif isinstance(node, list):
        for value in node:
            found |= keywords(value)
    return found


@pytest.mark.parametrize("name", HANDLERS)
def test_strict_schema_has_no_refs_or_unsupported_keywords(name: str) -> None:
    """NB-14: self-contained; keywords strict mode rejects are gone."""
    schema = HANDLERS[name].strict_schema()

    assert not keywords(schema) & FORBIDDEN_KEYWORDS
    json.dumps(schema)


@pytest.mark.parametrize("name", HANDLERS)
def test_strict_schema_is_valid_json_schema(name: str) -> None:
    """NB-14: the document itself is a valid JSON Schema."""
    jsonschema = pytest.importorskip("jsonschema")

    jsonschema.Draft202012Validator.check_schema(HANDLERS[name].strict_schema())


def test_optional_fields_are_nullable_and_required_ones_are_not() -> None:
    """NB-14: optional -> `anyOf [..., null]`; required stays plain."""
    schema = quiz.HANDLER.strict_schema()

    question = schema["properties"]["questions"]["items"]["properties"]
    assert {"type": "null"} in question["hint"]["anyOf"]
    assert {"type": "null"} in question["difficulty"]["anyOf"]
    assert "anyOf" not in question["prompt"]
    assert question["type"]["enum"] == ["single", "multiple", "true_false"]


@pytest.mark.parametrize("kind", sorted(supported_kinds()))
def test_strict_schema_stays_within_the_providers_union_limit(
    kind: ArtifactKind,
) -> None:
    """Anthropic answers HTTP 400 to more than 16 nullable or union-typed fields."""
    assert count_unions(handler_for(kind).strict_schema()) <= MAX_UNION_PARAMETERS


def test_slides_revise_schema_stays_within_the_providers_union_limit() -> None:
    """The revise answer reuses the slide model, so it shares the limit."""
    assert count_unions(revise_schema()) <= MAX_UNION_PARAMETERS


def test_not_null_fields_are_plain_in_the_schema_but_optional_in_an_edit() -> None:
    """The model writes "" or [] in columns and quotes; an edit may still send null."""
    slide = slides.HANDLER.strict_schema()["properties"]["slides"]["items"]
    left = slide["properties"]["left"]["anyOf"][0]["properties"]
    quote = slide["properties"]["quote"]["anyOf"][0]["properties"]

    assert left["heading"] == {"description": "At most 4 words.", "type": "string"}
    assert left["bullets"]["type"] == "array" and "anyOf" not in left["bullets"]
    assert quote["attribution"]["type"] == "string"
    assert {"type": "null"} in slide["properties"]["left"]["anyOf"]
    edit = slides.SlideOut.model_validate(
        {
            "layout": "two_columns",
            "left": {"heading": None, "bullets": None},
            "quote": {"text": "A line.", "attribution": None},
        }
    )
    assert edit.left is not None and edit.left.heading is None


def test_quiz_schema_has_the_fields_of_the_contract() -> None:
    """NB-14: QuizQuestion of § 4.4."""
    schema = quiz.HANDLER.strict_schema()

    question = schema["properties"]["questions"]["items"]
    assert set(question["properties"]) == {
        "id",
        "type",
        "prompt",
        "options",
        "correct",
        "explanation",
        "hint",
        "difficulty",
        "topic",
        "refs",
    }
    assert set(question["properties"]["options"]["items"]["properties"]) == {
        "id",
        "text",
    }


def test_slides_schema_lists_the_eight_layouts() -> None:
    """NB-14: layouts of § 3.4.6 plus the agenda."""
    schema = slides.HANDLER.strict_schema()

    layout = schema["properties"]["slides"]["items"]["properties"]["layout"]
    assert layout["enum"] == [
        "title",
        "agenda",
        "section",
        "bullets",
        "two_columns",
        "quote",
        "table",
        "summary",
    ]


def test_infographic_schema_lists_the_eight_block_types() -> None:
    """NB-14: block types of § 3.4.7."""
    schema = infographic.HANDLER.strict_schema()

    kind = schema["properties"]["blocks"]["items"]["properties"]["type"]
    assert set(kind["enum"]) == {
        "stat",
        "steps",
        "comparison",
        "list",
        "timeline",
        "definition",
        "quote",
        "callout",
    }


def test_data_table_schema_writes_cells_as_pairs() -> None:
    """NB-14: a strict schema cannot hold an object with dynamic keys."""
    schema = data_table.HANDLER.strict_schema()

    cells = schema["properties"]["rows"]["items"]["properties"]["cells"]
    assert cells["type"] == "array"
    assert set(cells["items"]["properties"]) == {"key", "value"}


@pytest.mark.parametrize("name", HANDLERS)
def test_a_complete_sample_validates_against_the_strict_schema(name: str) -> None:
    """NB-14: documents of the schema's shape are accepted by the schema."""
    jsonschema = pytest.importorskip("jsonschema")

    jsonschema.validate(SAMPLES[name], HANDLERS[name].strict_schema())


@pytest.mark.parametrize("name", HANDLERS)
def test_an_extra_property_is_rejected_by_the_strict_schema(name: str) -> None:
    """NB-14: additionalProperties false at the top level."""
    jsonschema = pytest.importorskip("jsonschema")
    sample = {**SAMPLES[name], "surprise": 1}

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(sample, HANDLERS[name].strict_schema())


@pytest.mark.parametrize("name", HANDLERS)
def test_a_sample_valid_for_the_schema_is_processed(name: str) -> None:
    """NB-14: what the schema allows, `process` turns into stored content."""
    handler = HANDLERS[name]

    out = handler.process(SAMPLES[name], handler.parse_options({}), CTX)

    assert out.title == SAMPLES[name]["title"]
    assert out.content["title"] == out.title
    assert out.refs_index
    json.dumps(out.content)


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        (ArtifactKind.QUIZ, "quiz"),
        (ArtifactKind.DATA_TABLE, "data_table"),
        (ArtifactKind.SLIDES, "slides"),
        (ArtifactKind.INFOGRAPHIC, "infographic"),
    ],
)
def test_the_registry_finds_each_handler_by_kind(kind: ArtifactKind, name: str) -> None:
    """NB-14: `handler_for` loads `kinds/<name>.py` and returns its HANDLER."""
    handler = handler_for(kind)

    assert handler is HANDLERS[name]
    assert handler.kind is kind
    assert handler.schema_name == f"nb_{name}"
