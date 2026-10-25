"""LMS-6, LMS-13: outline operations are pure and never mutate their input."""

import copy
from collections.abc import Iterator
from uuid import UUID

from app.modules.lms.domain.authoring.errors import OutlineError
from app.modules.lms.domain.authoring.hashing import outline_hash
from app.modules.lms.domain.authoring.outline import (
    OUTLINE_OPS_ADAPTER,
    AddSection,
    MoveSection,
    MoveStep,
    RemoveSection,
    RemoveStep,
    RenameSection,
    add_step,
    apply_ops,
    empty_outline,
    has_section,
    step_ids_in,
)
from app.shared.ids import new_id

import pytest

STEP_A, STEP_B, STEP_C = new_id(), new_id(), new_id()


def _ids() -> Iterator[str]:
    for n in range(1, 100):
        yield f"sec{n:05d}"


def _outline() -> dict[str, object]:
    return {
        "sections": [
            {"id": "s1", "title": "Limits", "steps": [str(STEP_A), str(STEP_B)]},
            {"id": "s2", "title": "Derivatives", "steps": [str(STEP_C)]},
        ]
    }


def _apply(ops: list[object]) -> tuple[dict[str, object], list[str]]:
    ids = _ids()
    return apply_ops(
        _outline(),
        ops,
        course_step_ids={STEP_A, STEP_B, STEP_C},
        section_id_factory=lambda: next(ids),
    )


def _titles(outline: dict[str, object]) -> list[str]:
    return [s["title"] for s in outline["sections"]]


def test_add_section_appends_with_a_new_id() -> None:
    """The server creates section IDs."""
    outline, created = _apply([AddSection(op="add_section", title="Integrals")])

    assert created == ["sec00001"]
    assert _titles(outline) == ["Limits", "Derivatives", "Integrals"]


def test_add_section_at_a_position() -> None:
    """A position inserts instead of appending."""
    outline, _ = _apply([AddSection(op="add_section", title="Intro", position=0)])

    assert _titles(outline) == ["Intro", "Limits", "Derivatives"]


def test_add_section_never_reuses_an_existing_id() -> None:
    """A colliding ID from the factory is skipped."""
    values = iter(["s1", "fresh"])

    outline, created = apply_ops(
        _outline(),
        [AddSection(op="add_section", title="X")],
        course_step_ids=set(),
        section_id_factory=lambda: next(values),
    )

    assert created == ["fresh"]
    assert len(outline["sections"]) == 3


def test_rename_and_move_section() -> None:
    """Sections can be renamed and reordered."""
    outline, _ = _apply(
        [
            RenameSection(op="rename_section", section_id="s2", title="Rules"),
            MoveSection(op="move_section", section_id="s2", position=0),
        ]
    )

    assert _titles(outline) == ["Rules", "Limits"]


def test_remove_section_requires_it_to_be_empty() -> None:
    """Only an empty section can be removed."""
    with pytest.raises(OutlineError) as caught:
        _apply([RemoveSection(op="remove_section", section_id="s1")])

    assert caught.value.params["reason"] == "section-not-empty"
    outline, _ = _apply(
        [
            RemoveStep(op="remove_step", step_id=STEP_C),
            RemoveSection(op="remove_section", section_id="s2"),
        ]
    )
    assert _titles(outline) == ["Limits"]


def test_move_step_between_sections_and_within_a_section() -> None:
    """A step moves to the given index of the target section."""
    outline, _ = _apply(
        [
            MoveStep(op="move_step", step_id=STEP_A, to_section_id="s2", position=0),
            MoveStep(op="move_step", step_id=STEP_C, to_section_id="s2", position=5),
        ]
    )

    assert step_ids_in(outline) == [STEP_B, STEP_A, STEP_C]
    assert outline["sections"][1]["steps"] == [str(STEP_A), str(STEP_C)]


def test_remove_step_only_removes_it_from_the_outline() -> None:
    """The step stays a course step and can be moved back later."""
    outline, _ = _apply([RemoveStep(op="remove_step", step_id=STEP_B)])
    assert STEP_B not in step_ids_in(outline)

    again, _ = apply_ops(
        outline,
        [MoveStep(op="move_step", step_id=STEP_B, to_section_id="s1", position=0)],
        course_step_ids={STEP_A, STEP_B, STEP_C},
    )

    assert step_ids_in(again)[0] == STEP_B


def test_a_step_of_another_course_cannot_be_moved_in() -> None:
    """`move_step` re-adds only steps that belong to the course."""
    with pytest.raises(OutlineError) as caught:
        _apply(
            [MoveStep(op="move_step", step_id=new_id(), to_section_id="s1", position=0)]
        )

    assert caught.value.params["reason"] == "step-not-found"


@pytest.mark.parametrize(
    "op",
    [
        RenameSection(op="rename_section", section_id="nope", title="x"),
        MoveSection(op="move_section", section_id="nope", position=0),
        RemoveSection(op="remove_section", section_id="nope"),
        MoveStep(op="move_step", step_id=STEP_A, to_section_id="nope", position=0),
        RemoveStep(op="remove_step", step_id=new_id()),
    ],
)
def test_operations_on_missing_things_are_rejected(op: object) -> None:
    """A bad reference is a typed outline error, never a silent no-op."""
    with pytest.raises(OutlineError):
        _apply([op])


def test_apply_ops_does_not_mutate_its_input() -> None:
    """The caller keeps the old outline to compare hashes."""
    before = _outline()
    snapshot = copy.deepcopy(before)

    apply_ops(
        before,
        [AddSection(op="add_section", title="X")],
        course_step_ids=set(),
    )

    assert before == snapshot


def test_add_step_inserts_into_a_section() -> None:
    """New steps go to the end or to a position of their section."""
    outline = add_step(_outline(), "s1", STEP_C, 0)

    assert outline["sections"][0]["steps"][0] == str(STEP_C)
    assert has_section(outline, "s2")
    assert not has_section(outline, "zzz")


def test_ops_parse_from_json_by_their_op_name() -> None:
    """The HTTP body is a list of discriminated operations."""
    ops = OUTLINE_OPS_ADAPTER.validate_python(
        [
            {"op": "add_section", "title": "  Intro  "},
            {
                "op": "move_step",
                "step_id": str(STEP_A),
                "to_section_id": "s1",
                "position": 2,
            },
        ]
    )

    assert isinstance(ops[0], AddSection) and ops[0].title == "Intro"
    assert isinstance(ops[1], MoveStep) and isinstance(ops[1].step_id, UUID)


def test_outline_hash_changes_with_meta_or_outline_only() -> None:
    """Pending outline changes are detected by comparing this hash (LMS-7)."""
    meta = {"title": "Calculus", "description": ""}
    base = outline_hash(meta, empty_outline())

    assert outline_hash(dict(meta), empty_outline()) == base
    assert outline_hash({**meta, "title": "Calculus 2"}, empty_outline()) != base
    assert (
        outline_hash(meta, {"sections": [{"id": "a", "title": "A", "steps": []}]})
        != base
    )
