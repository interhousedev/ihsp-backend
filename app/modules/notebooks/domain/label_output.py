"""The model's answer for auto labels: strict schema and defensive parsing.

The JSON is repaired softly: unknown source keys and unknown label keys are dropped,
names are cut to 40 characters, repeated names merged, labels cut to 12 and a source
gets at most 2 labels. Only an answer without any usable label is an
`OutputInvalidError`.
"""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final

from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.guide import single_emoji
from app.modules.notebooks.domain.labels import (
    AUTO_LABELS_PER_SOURCE,
    DEFAULT_LABEL_EMOJI,
    LABEL_EMOJI_MAX_CHARS,
    LABEL_NAME_MAX_CHARS,
    MAX_LABELS,
)

from pydantic import BaseModel, Field

LABELS_SCHEMA_NAME: Final = "nb_labels"


class LabelOut(BaseModel):
    """One topic label the model proposes."""

    key: str = Field(description="Short id such as l1, l2, l3, used in assignments")
    name: str = Field(description="1 to 3 words, at most 40 characters")
    emoji: str = Field(description="exactly one emoji that fits the topic")


class AssignmentOut(BaseModel):
    """The labels of one source."""

    source: str = Field(description="The key of the source, such as s1")
    labels: list[str] = Field(description="1 or 2 label keys, at most 2")


class LabelsOutput(BaseModel):
    """The JSON of the auto labels (``nb_labels``); it has no union-typed field."""

    labels: list[LabelOut] = Field(description="3 to 12 topics, at most 12")
    assignments: list[AssignmentOut] = Field(
        description="one entry for every source of the input"
    )


@dataclass(frozen=True, slots=True)
class ParsedLabel:
    """A cleaned label: its key in the answer, name and emoji."""

    key: str
    name: str
    emoji: str


@dataclass(frozen=True, slots=True)
class ParsedLabels:
    """Cleaned labels and, for each source key, the keys of its labels (in order)."""

    labels: list[ParsedLabel]
    assignments: dict[str, list[str]]


def labels_schema() -> dict[str, Any]:
    """Strict JSON schema of the auto labels."""
    return to_strict_schema(LabelsOutput)


def _text(value: Any) -> str:
    """A string field with its whitespace collapsed; anything else is empty."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def _name(value: Any) -> str:
    """A label name cut to its limit; an ellipsis marks a cut."""
    text = _text(value)
    if len(text) <= LABEL_NAME_MAX_CHARS:
        return text
    return text[: LABEL_NAME_MAX_CHARS - 1].rstrip() + "…"


def _emoji(value: Any) -> str:
    """The first emoji of the field, else the default tag."""
    found = single_emoji(value) if isinstance(value, str) else None
    if found is None or len(found) > LABEL_EMOJI_MAX_CHARS:
        return DEFAULT_LABEL_EMOJI
    return found


def _clean_labels(raw: Any) -> tuple[list[ParsedLabel], dict[str, str]]:
    """The labels (repeated names merged, at most 12) and key -> kept key."""
    labels: list[ParsedLabel] = []
    by_name: dict[str, str] = {}
    alias: dict[str, str] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = _name(item.get("name"))
        key = _text(item.get("key")) or name
        if not name or not key or key in alias:
            continue
        kept = by_name.get(name.casefold())
        if kept is None:
            if len(labels) >= MAX_LABELS:
                continue
            labels.append(ParsedLabel(key, name, _emoji(item.get("emoji"))))
            by_name[name.casefold()] = key
            kept = key
        alias[key] = kept
    return labels, alias


def _clean_assignments(
    raw: Any, alias: dict[str, str], source_keys: Collection[str]
) -> dict[str, list[str]]:
    """Known sources with known labels, at most 2 each, repeated entries merged."""
    assignments: dict[str, list[str]] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        source = _text(item.get("source"))
        keys = item.get("labels")
        if source not in source_keys or not isinstance(keys, list):
            continue
        chosen = assignments.setdefault(source, [])
        for key in keys:
            kept = alias.get(_text(key))
            if (
                kept is not None
                and kept not in chosen
                and len(chosen) < AUTO_LABELS_PER_SOURCE
            ):
                chosen.append(kept)
    return {source: chosen for source, chosen in assignments.items() if chosen}


def parse_labels(data: Any, source_keys: Collection[str]) -> ParsedLabels:
    """Validate and repair the model's labels.

    Labels that no source uses are dropped.

    Raises:
        OutputInvalidError: The answer has no label that a known source carries.
    """
    if not isinstance(data, dict):
        raise OutputInvalidError(["the answer must be one JSON object"])
    labels, alias = _clean_labels(data.get("labels"))
    assignments = _clean_assignments(data.get("assignments"), alias, source_keys)
    used = {key for keys in assignments.values() for key in keys}
    labels = [label for label in labels if label.key in used]
    if not labels:
        raise OutputInvalidError(["no label is assigned to a known source"])
    return ParsedLabels(labels=labels, assignments=assignments)
