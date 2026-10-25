"""LMS-7: pending changes come from hashes, not from content diffing."""

from uuid import UUID

from app.modules.lms.domain.authoring.enums import StepChange, StepVia
from app.modules.lms.domain.authoring.manifest import ManifestStep
from app.modules.lms.domain.authoring.pending import StepSnapshot, compute_pending
from app.shared.ids import new_id


def _snap(
    step_id: UUID,
    *,
    draft: str = "h1",
    live: str | None = "h1",
    revision: UUID | None = None,
    via: StepVia = StepVia.UI,
) -> StepSnapshot:
    pinned = revision or (new_id() if live is not None else None)
    return StepSnapshot(step_id, f"Step {str(step_id)[-4:]}", draft, live, pinned, via)


def _live(step_id: UUID, title: str = "Old") -> ManifestStep:
    return ManifestStep("s1", step_id, new_id(), title)


def _outline(*ids: UUID) -> dict[str, object]:
    return {"sections": [{"id": "s1", "title": "S", "steps": [str(i) for i in ids]}]}


def _pending(
    snapshots: list[StepSnapshot],
    outline_ids: list[UUID],
    live: list[ManifestStep],
    *,
    outline_hash: str = "o1",
    live_outline_hash: str | None = "o1",
):  # noqa: ANN202 - helper
    return compute_pending(
        draft_seq=7,
        outline_hash=outline_hash,
        live_outline_hash=live_outline_hash,
        outline=_outline(*outline_ids),
        snapshots={s.step_id: s for s in snapshots},
        live=live,
    )


def test_unchanged_course_has_nothing_pending() -> None:
    """Same hashes everywhere: the Publish button stays disabled."""
    a = new_id()

    pending = _pending([_snap(a)], [a], [_live(a)])

    assert pending.is_empty
    assert pending.count == 0
    assert pending.draft_seq == 7


def test_step_without_live_revision_is_added() -> None:
    """A step that was never published is new."""
    a, b = new_id(), new_id()

    pending = _pending(
        [_snap(a), _snap(b, live=None)], [a, b], [_live(a)], outline_hash="o2"
    )

    assert [(s.step_id, s.change) for s in pending.steps] == [(b, StepChange.ADDED)]
    assert pending.outline_changed


def test_step_with_a_different_hash_is_changed() -> None:
    """draft_hash <> live_hash means changed."""
    a = new_id()

    pending = _pending([_snap(a, draft="h2")], [a], [_live(a)])

    assert [s.change for s in pending.steps] == [StepChange.CHANGED]
    assert not pending.outline_changed


def test_live_step_missing_from_the_outline_is_removed() -> None:
    """Removing a step from the outline is a pending removal."""
    a, b = new_id(), new_id()

    pending = _pending([_snap(a)], [a], [_live(a), _live(b, "Gone")], outline_hash="o2")

    assert [(s.step_id, s.title, s.change) for s in pending.steps] == [
        (b, "Gone", StepChange.REMOVED)
    ]


def test_mcp_flag_is_reported_for_pending_steps_only() -> None:
    """The "via MCP" badge applies to pending steps, not to published ones."""
    a, b = new_id(), new_id()

    pending = _pending(
        [_snap(a, draft="h2", via=StepVia.MCP), _snap(b, via=StepVia.MCP)],
        [a, b],
        [_live(a), _live(b)],
    )

    assert [(s.step_id, s.via_mcp) for s in pending.steps] == [(a, True)]


def test_outline_change_alone_is_pending() -> None:
    """Renaming a section changes the outline hash only."""
    a = new_id()

    pending = _pending([_snap(a)], [a], [_live(a)], outline_hash="o2")

    assert pending.steps == ()
    assert pending.outline_changed
    assert pending.count == 1
    assert not pending.is_empty


def test_added_step_is_not_counted_twice() -> None:
    """The outline change of an added step is explained by the step."""
    a, b = new_id(), new_id()

    pending = _pending(
        [_snap(a), _snap(b, live=None)], [a, b], [_live(a)], outline_hash="o2"
    )

    assert pending.count == 1


def test_never_published_course_has_its_outline_pending() -> None:
    """With no live version every outline differs from `None`."""
    pending = _pending([], [], [], live_outline_hash=None)

    assert pending.outline_changed
    assert pending.of(StepChange.ADDED) == []
