"""G12: the strict schema and the defensive parsing of the auto labels answer."""

from typing import Any

from app.modules.notebooks.domain.artifacts.strict import (
    MAX_UNION_PARAMETERS,
    count_unions,
)
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.label_output import (
    ParsedLabel,
    labels_schema,
    parse_labels,
)
from app.modules.notebooks.domain.labels import DEFAULT_LABEL_EMOJI

import pytest

SOURCES = {"s1", "s2", "s3"}


def answer(labels: list[Any], assignments: list[Any]) -> dict[str, Any]:
    """A model answer."""
    return {"labels": labels, "assignments": assignments}


def label(key: str, name: str, emoji: str = "🧬") -> dict[str, str]:
    """A label of an answer."""
    return {"key": key, "name": name, "emoji": emoji}


def test_the_schema_has_no_union_typed_parameter() -> None:
    """Anthropic answers HTTP 400 to more than 16 nullable or union-typed fields."""
    schema = labels_schema()

    assert count_unions(schema) == 0 <= MAX_UNION_PARAMETERS
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"labels", "assignments"}


def test_the_schema_asks_for_key_name_emoji_and_source_labels() -> None:
    """The contract of the answer: labels and assignments."""
    properties = labels_schema()["properties"]

    assert set(properties["labels"]["items"]["properties"]) == {"key", "name", "emoji"}
    assert set(properties["assignments"]["items"]["properties"]) == {"source", "labels"}


def test_a_good_answer_is_kept_as_it_is() -> None:
    """Labels in order, assignments by source key."""
    parsed = parse_labels(
        answer(
            [label("l1", "Cells"), label("l2", "Energy", "⚡")],
            [
                {"source": "s1", "labels": ["l1"]},
                {"source": "s2", "labels": ["l1", "l2"]},
            ],
        ),
        SOURCES,
    )

    assert parsed.labels == [
        ParsedLabel("l1", "Cells", "🧬"),
        ParsedLabel("l2", "Energy", "⚡"),
    ]
    assert parsed.assignments == {"s1": ["l1"], "s2": ["l1", "l2"]}


def test_unknown_source_keys_and_unknown_label_keys_are_dropped() -> None:
    """The model may invent keys; they are ignored."""
    parsed = parse_labels(
        answer(
            [label("l1", "Cells")],
            [
                {"source": "s99", "labels": ["l1"]},
                {"source": "s1", "labels": ["l1", "l7"]},
            ],
        ),
        SOURCES,
    )

    assert parsed.assignments == {"s1": ["l1"]}


def test_a_source_gets_at_most_two_labels() -> None:
    """A third label of one source is dropped, also across repeated entries."""
    labels = [label(f"l{n}", f"Topic {n}") for n in range(1, 5)]

    parsed = parse_labels(
        answer(
            labels,
            [
                {"source": "s1", "labels": ["l1", "l2", "l3"]},
                {"source": "s1", "labels": ["l4"]},
            ],
        ),
        SOURCES,
    )

    assert parsed.assignments == {"s1": ["l1", "l2"]}
    assert [item.key for item in parsed.labels] == ["l1", "l2"]


def test_at_most_twelve_labels_are_kept() -> None:
    """The 13th label and its assignments are dropped."""
    labels = [label(f"l{n}", f"Topic {n}") for n in range(1, 16)]
    assignments = [{"source": "s1", "labels": ["l1", "l13"]}]

    parsed = parse_labels(answer(labels, assignments), SOURCES)

    assert parsed.assignments == {"s1": ["l1"]}
    assert len(parsed.labels) == 1


def test_twelve_labels_survive_when_sources_use_them() -> None:
    """The cap is 12, not fewer."""
    names = [f"Topic {n}" for n in range(1, 16)]
    labels = [label(f"l{n}", name) for n, name in enumerate(names, start=1)]
    keys = {f"s{n}" for n in range(1, 16)}
    assignments = [{"source": f"s{n}", "labels": [f"l{n}"]} for n in range(1, 16)]

    parsed = parse_labels(answer(labels, assignments), keys)

    assert [item.name for item in parsed.labels] == names[:12]


def test_names_are_cut_to_forty_characters_and_trimmed() -> None:
    """Long names end with an ellipsis; whitespace is collapsed."""
    parsed = parse_labels(
        answer(
            [label("l1", "  The   structure of the cell and all its   parts " * 2)],
            [{"source": "s1", "labels": ["l1"]}],
        ),
        SOURCES,
    )

    name = parsed.labels[0].name
    assert len(name) == 40 and name.endswith("…") and "  " not in name


def test_the_same_name_in_any_case_is_one_label() -> None:
    """Repeated names are merged; assignments follow the first label."""
    parsed = parse_labels(
        answer(
            [label("l1", "Cells"), label("l2", " cells ")],
            [{"source": "s1", "labels": ["l2"]}, {"source": "s2", "labels": ["l1"]}],
        ),
        SOURCES,
    )

    assert [item.key for item in parsed.labels] == ["l1"]
    assert parsed.assignments == {"s1": ["l1"], "s2": ["l1"]}


def test_a_label_no_source_uses_is_dropped() -> None:
    """No empty topics."""
    parsed = parse_labels(
        answer(
            [label("l1", "Cells"), label("l2", "Unused")],
            [{"source": "s1", "labels": ["l1"]}],
        ),
        SOURCES,
    )

    assert [item.name for item in parsed.labels] == ["Cells"]


def test_a_missing_or_wrong_emoji_becomes_the_default_tag() -> None:
    """The first emoji of the field, else the tag."""
    parsed = parse_labels(
        answer(
            [label("l1", "Cells", "not an emoji"), label("l2", "Energy", "⚡ and text")],
            [{"source": "s1", "labels": ["l1", "l2"]}],
        ),
        SOURCES,
    )

    assert [item.emoji for item in parsed.labels] == [DEFAULT_LABEL_EMOJI, "⚡"]


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"labels": "x", "assignments": []},
        answer([], []),
        answer([label("l1", "Cells")], []),
        answer([label("l1", "Cells")], [{"source": "s9", "labels": ["l1"]}]),
        answer([{"key": "l1"}], [{"source": "s1", "labels": ["l1"]}]),
        answer([label("l1", "Cells")], [{"source": "s1", "labels": "l1"}]),
    ],
)
def test_an_answer_without_a_usable_label_is_invalid(data: Any) -> None:
    """Nothing to write: the job marks the run failed."""
    with pytest.raises(OutputInvalidError):
        parse_labels(data, SOURCES)
