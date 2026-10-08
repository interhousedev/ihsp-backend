"""LMS-11: comparing versions by revision IDs; manifest reading and writing."""

from uuid import UUID

from app.modules.lms.domain.authoring.compare import compare_manifests
from app.modules.lms.domain.authoring.enums import StepChange
from app.modules.lms.domain.authoring.manifest import (
    ManifestStep,
    build_manifest,
    manifest_steps,
    outline_from_manifest,
    parse_manifest,
)
from app.shared.ids import new_id


def _step(
    step_id: UUID, revision: UUID, title: str = "T", section: str = "s1"
) -> ManifestStep:
    return ManifestStep(section, step_id, revision, title)


def test_same_changed_added_and_removed_steps() -> None:
    """Same revision is `same`; otherwise changed, added or removed."""
    same, changed, removed, added = new_id(), new_id(), new_id(), new_id()
    rev = {name: new_id() for name in ("same", "a", "b", "removed", "added")}
    first = [
        _step(same, rev["same"]),
        _step(changed, rev["a"]),
        _step(removed, rev["removed"]),
    ]
    second = [
        _step(same, rev["same"]),
        _step(changed, rev["b"]),
        _step(added, rev["added"]),
    ]

    rows = compare_manifests(first, second)

    assert [(r.step_id, r.change) for r in rows] == [
        (same, StepChange.SAME),
        (changed, StepChange.CHANGED),
        (added, StepChange.ADDED),
        (removed, StepChange.REMOVED),
    ]
    changed_row = rows[1]
    assert (changed_row.revision_a, changed_row.revision_b) == (rev["a"], rev["b"])
    assert rows[2].revision_a is None
    assert rows[3].revision_b is None


def test_manifest_round_trip_with_the_draft_outline() -> None:
    """build_manifest then outline_from_manifest returns the draft outline."""
    a, b = new_id(), new_id()
    draft = {
        "sections": [
            {"id": "s1", "title": "Limits", "steps": [str(a)]},
            {"id": "s2", "title": "Empty", "steps": []},
            {"id": "s3", "title": "More", "steps": [str(b)]},
        ]
    }
    revisions = {a: new_id(), b: new_id()}

    stored = build_manifest(draft, revisions, {a: "A", b: "B"})
    sections = parse_manifest(stored)

    assert outline_from_manifest(sections) == draft
    assert [(s.step_id, s.revision_id, s.title) for s in manifest_steps(sections)] == [
        (a, revisions[a], "A"),
        (b, revisions[b], "B"),
    ]
    assert stored["sections"][0]["steps"][0]["step_id"] == str(a)


def test_a_bare_list_of_sections_is_read_too() -> None:
    """Readers accept both stored shapes of a version outline."""
    a, rev = new_id(), new_id()
    bare = [
        {
            "id": "s1",
            "title": "S",
            "steps": [{"step_id": str(a), "revision_id": str(rev), "title": "A"}],
        }
    ]

    assert parse_manifest(bare) == parse_manifest({"sections": bare})
    assert parse_manifest(None) == []
