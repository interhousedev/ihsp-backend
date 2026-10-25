"""What an auto run changes: the pure merge of the model's labels into a notebook.

Rules: the student's labels and links are never touched; the run replaces only the
`auto` links of the sources it covered; a model label with the name of an existing
label (any origin, any case) reuses it; `auto` labels that carry no link afterwards
are removed; a notebook never holds more than 12 labels and a source never more than
3 links.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.modules.notebooks.domain.label_output import ParsedLabel, ParsedLabels
from app.modules.notebooks.domain.labels import (
    MAX_LABELS,
    MAX_LABELS_PER_SOURCE,
    LabelLink,
    LabelOrigin,
    SourceLabel,
)


@dataclass(frozen=True, slots=True)
class LabelPlan:
    """The writes of one run, in the order they must be applied."""

    unlink_auto_of: list[UUID] = field(default_factory=list)  # sources
    delete_labels: list[UUID] = field(default_factory=list)
    new_labels: list[SourceLabel] = field(default_factory=list)
    new_links: list[LabelLink] = field(default_factory=list)


def _reuse(
    parsed: ParsedLabels, existing: Mapping[str, SourceLabel]
) -> dict[str, SourceLabel]:
    """Model key -> the existing label with the same name."""
    return {
        label.key: existing[label.name.casefold()]
        for label in parsed.labels
        if label.name.casefold() in existing
    }


def _create(
    missing: Sequence[ParsedLabel],
    room: int,
    *,
    notebook_id: UUID,
    start: int,
    now: datetime,
    new_id: Callable[[], UUID],
) -> dict[str, SourceLabel]:
    """New `auto` labels for the model labels that match nothing, up to `room`."""
    created: dict[str, SourceLabel] = {}
    for offset, label in enumerate(missing[: max(room, 0)]):
        created[label.key] = SourceLabel(
            id=new_id(),
            notebook_id=notebook_id,
            name=label.name,
            emoji=label.emoji,
            position=start + offset,
            origin=LabelOrigin.AUTO,
            created_at=now,
        )
    return created


def _link(
    parsed: ParsedLabels,
    resolved: Mapping[str, SourceLabel],
    sources: Mapping[str, UUID],
    kept: Sequence[LabelLink],
) -> list[LabelLink]:
    """The `auto` links to add; a source already full or already linked is skipped."""
    held: dict[UUID, set[UUID]] = {}
    for link in kept:
        held.setdefault(link.source_id, set()).add(link.label_id)
    added: list[LabelLink] = []
    for source_key, label_keys in parsed.assignments.items():
        source_id = sources.get(source_key)
        if source_id is None:  # the source was removed while the model worked
            continue
        have = held.setdefault(source_id, set())
        for label_key in label_keys:
            label = resolved.get(label_key)
            if label is None or label.id in have or len(have) >= MAX_LABELS_PER_SOURCE:
                continue
            have.add(label.id)
            added.append(LabelLink(source_id, label.id, LabelOrigin.AUTO))
    return added


def plan_labels(
    *,
    notebook_id: UUID,
    labels: Sequence[SourceLabel],
    links: Sequence[LabelLink],
    parsed: ParsedLabels,
    sources: Mapping[str, UUID],
    now: datetime,
    new_id: Callable[[], UUID],
) -> LabelPlan:
    """Merge the model's labels into the notebook's.

    Args:
        notebook_id: The notebook.
        labels: Its labels now.
        links: Its links now.
        parsed: The cleaned answer of the model.
        sources: Source key of the prompt -> source id, for the sources the run
            covered that still exist.
        now: Creation time of new labels.
        new_id: Makes the id of a new label.
    """
    covered = set(sources.values())
    kept = [
        link
        for link in links
        if link.origin is LabelOrigin.MANUAL or link.source_id not in covered
    ]
    linked = {link.label_id for link in kept}
    existing = {label.name.casefold(): label for label in labels}
    resolved = _reuse(parsed, existing)
    reused = {label.id for label in resolved.values()}
    orphans = [
        label
        for label in labels
        if label.origin is LabelOrigin.AUTO
        and label.id not in linked
        and label.id not in reused
    ]
    missing = [label for label in parsed.labels if label.key not in resolved]
    created = _create(
        missing,
        MAX_LABELS - (len(labels) - len(orphans)),
        notebook_id=notebook_id,
        start=max((label.position for label in labels), default=0) + 1,
        now=now,
        new_id=new_id,
    )
    added = _link(parsed, {**resolved, **created}, sources, kept)
    used = linked | {link.label_id for link in added}
    stale = [
        label.id
        for label in labels
        if label.origin is LabelOrigin.AUTO and label.id not in used
    ]
    return LabelPlan(
        unlink_auto_of=sorted(covered),
        delete_labels=stale,
        new_labels=[label for label in created.values() if label.id in used],
        new_links=added,
    )
