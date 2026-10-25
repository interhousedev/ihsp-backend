"""Builders shared by the kind tests: context pack, process context, schema check."""

from collections.abc import Sequence
from typing import Any

from app.modules.notebooks.domain.artifacts.handler import ProcessContext
from app.modules.notebooks.domain.context import (
    ContextPack,
    PackPassage,
    PackSource,
    make_label,
)
from app.modules.notebooks.domain.enums import SourceKind
from app.shared.ids import new_id


def make_pack(
    shape: Sequence[int] = (6,), titles: Sequence[str] | None = None
) -> ContextPack:
    """A pack with one source per entry of ``shape`` and that many passages each."""
    sources: list[PackSource] = []
    labels: dict[str, PackPassage] = {}
    source_map = {}
    names: dict[Any, tuple[str, SourceKind]] = {}
    for n, count in enumerate(shape, start=1):
        source_id = new_id()
        title = titles[n - 1] if titles else f"Source {n}"
        passages = tuple(
            PackPassage(
                label=make_label(n, seq),
                passage_id=new_id(),
                source_id=source_id,
                seq=seq,
                text=f"Text of passage {seq} of source {n}.  It has   spaces.",
                token_estimate=12,
                page=seq if n == 1 else None,
            )
            for seq in range(1, count + 1)
        )
        sources.append(PackSource(n, source_id, title, SourceKind.FILE, passages))
        labels.update({p.label: p for p in passages})
        source_map[f"S{n}"] = source_id
        names[source_id] = (title, SourceKind.FILE)
    return ContextPack(
        sources=tuple(sources),
        mode="full",
        token_estimate=sum(shape) * 12,
        labels=labels,
        source_map=source_map,
        titles=names,
    )


def make_ctx(pack: ContextPack | None = None, language: str = "en") -> ProcessContext:
    """A process context for ``pack`` (a default pack when omitted)."""
    return ProcessContext(pack=pack or make_pack(), language=language, seed=7)


def assert_strict(schema: Any) -> None:
    """Objects require all properties, forbid extras; no ``$ref`` anywhere."""
    if isinstance(schema, list):
        for item in schema:
            assert_strict(item)
        return
    if not isinstance(schema, dict):
        return
    assert "$ref" not in schema and "$defs" not in schema
    if schema.get("type") == "object":
        properties = schema["properties"]
        assert schema["required"] == list(properties)
        assert schema["additionalProperties"] is False
        for sub in properties.values():
            assert_strict(sub)
        return
    for value in schema.values():
        assert_strict(value)
