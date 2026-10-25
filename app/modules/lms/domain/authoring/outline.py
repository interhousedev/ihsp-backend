"""The draft outline (sections with ordered step IDs) and edit operations on it."""

import copy
import secrets
from collections.abc import Callable, Collection, Iterable
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from app.modules.lms.domain.authoring.errors import OutlineError

from pydantic import BaseModel, Field, StringConstraints, TypeAdapter

Outline = dict[str, Any]
SectionIdFactory = Callable[[], str]

SECTION_ID_BYTES: Final = 6
SectionTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class AddSection(BaseModel):
    """Add an empty section (at the end unless `position` is given)."""

    op: Literal["add_section"]
    title: SectionTitle
    position: int | None = Field(default=None, ge=0)


class RenameSection(BaseModel):
    """Change the title of a section."""

    op: Literal["rename_section"]
    section_id: str
    title: SectionTitle


class MoveSection(BaseModel):
    """Move a section to a new index."""

    op: Literal["move_section"]
    section_id: str
    position: int = Field(ge=0)


class RemoveSection(BaseModel):
    """Remove an empty section."""

    op: Literal["remove_section"]
    section_id: str


class MoveStep(BaseModel):
    """Move a step to a section and index; also re-adds a removed step."""

    op: Literal["move_step"]
    step_id: UUID
    to_section_id: str
    position: int = Field(ge=0)


class RemoveStep(BaseModel):
    """Remove a step from the outline (the step itself is kept)."""

    op: Literal["remove_step"]
    step_id: UUID


OutlineOp = Annotated[
    AddSection | RenameSection | MoveSection | RemoveSection | MoveStep | RemoveStep,
    Field(discriminator="op"),
]
OUTLINE_OPS_ADAPTER: Final = TypeAdapter(list[OutlineOp])


def empty_outline() -> Outline:
    """Return an outline without sections."""
    return {"sections": []}


def new_section_id() -> str:
    """Return a random 8-character section ID."""
    return secrets.token_urlsafe(SECTION_ID_BYTES)


def sections_of(outline: Outline) -> list[dict[str, Any]]:
    """Return the list of sections of an outline."""
    sections: list[dict[str, Any]] = outline.get("sections", [])
    return sections


def step_ids_in(outline: Outline) -> list[UUID]:
    """Return every step ID in outline order."""
    return [UUID(s) for section in sections_of(outline) for s in section["steps"]]


def section_ids_in(outline: Outline) -> list[str]:
    """Return every section ID in outline order."""
    return [section["id"] for section in sections_of(outline)]


def has_section(outline: Outline, section_id: str) -> bool:
    """Return True if the outline has the section."""
    return section_id in section_ids_in(outline)


def add_step(
    outline: Outline, section_id: str, step_id: UUID, position: int | None
) -> Outline:
    """Return a copy of the outline with the step inserted into a section."""
    result = copy.deepcopy(outline)
    section = _find_section(sections_of(result), section_id)
    _insert(section["steps"], str(step_id), position)
    return result


def apply_ops(
    outline: Outline,
    ops: Iterable[Any],
    *,
    course_step_ids: Collection[UUID],
    section_id_factory: SectionIdFactory = new_section_id,
) -> tuple[Outline, list[str]]:
    """Apply operations to a copy of the outline.

    Args:
        outline: Current draft outline.
        ops: Validated `OutlineOp` objects, applied in order.
        course_step_ids: IDs of all steps of the course; `move_step` may re-add a
            step that is not in the outline only if it belongs to the course.
        section_id_factory: Source of new section IDs.

    Returns:
        The new outline and the IDs of the sections created by the operations.

    Raises:
        OutlineError: An operation does not apply to the outline.
    """
    result = copy.deepcopy(outline)
    sections = sections_of(result)
    created: list[str] = []
    for op in ops:
        _apply_one(sections, op, course_step_ids, section_id_factory, created)
    return result, created


# - - - Operations - - -


def _apply_one(
    sections: list[dict[str, Any]],
    op: Any,  # noqa: ANN401 - one of the OutlineOp models
    course_step_ids: Collection[UUID],
    section_id_factory: SectionIdFactory,
    created: list[str],
) -> None:
    if isinstance(op, AddSection):
        created.append(_add_section(sections, op, section_id_factory))
    elif isinstance(op, RenameSection):
        _find_section(sections, op.section_id)["title"] = op.title
    elif isinstance(op, MoveSection):
        _move_section(sections, op)
    elif isinstance(op, RemoveSection):
        _remove_section(sections, op)
    elif isinstance(op, MoveStep):
        _move_step(sections, op, course_step_ids)
    elif isinstance(op, RemoveStep):
        _remove_step(sections, op)
    else:
        raise OutlineError(params={"reason": "unknown-op"})


def _add_section(
    sections: list[dict[str, Any]], op: AddSection, section_id_factory: SectionIdFactory
) -> str:
    taken = {s["id"] for s in sections}
    new_id = section_id_factory()
    while new_id in taken:
        new_id = section_id_factory()
    _insert(sections, {"id": new_id, "title": op.title, "steps": []}, op.position)
    return new_id


def _move_section(sections: list[dict[str, Any]], op: MoveSection) -> None:
    section = _find_section(sections, op.section_id)
    sections.remove(section)
    _insert(sections, section, op.position)


def _remove_section(sections: list[dict[str, Any]], op: RemoveSection) -> None:
    section = _find_section(sections, op.section_id)
    if section["steps"]:
        raise OutlineError(
            params={"reason": "section-not-empty", "section_id": op.section_id}
        )
    sections.remove(section)


def _move_step(
    sections: list[dict[str, Any]], op: MoveStep, course_step_ids: Collection[UUID]
) -> None:
    target = _find_section(sections, op.to_section_id)
    step = str(op.step_id)
    if not _detach_step(sections, step) and op.step_id not in course_step_ids:
        raise OutlineError(params={"reason": "step-not-found", "step_id": step})
    _insert(target["steps"], step, op.position)


def _remove_step(sections: list[dict[str, Any]], op: RemoveStep) -> None:
    if not _detach_step(sections, str(op.step_id)):
        raise OutlineError(
            params={"reason": "step-not-in-outline", "step_id": str(op.step_id)}
        )


# - - - Helpers - - -


def _find_section(sections: list[dict[str, Any]], section_id: str) -> dict[str, Any]:
    for section in sections:
        if section["id"] == section_id:
            return section
    raise OutlineError(params={"reason": "section-not-found", "section_id": section_id})


def _detach_step(sections: list[dict[str, Any]], step: str) -> bool:
    """Remove the step from whichever section holds it; return True if found."""
    for section in sections:
        if step in section["steps"]:
            section["steps"].remove(step)
            return True
    return False


def _insert(items: list[Any], item: Any, position: int | None) -> None:  # noqa: ANN401
    if position is None or position >= len(items):
        items.append(item)
    else:
        items.insert(position, item)
