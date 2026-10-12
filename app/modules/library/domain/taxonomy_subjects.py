"""Subjects of the library: a librarian-managed tree with an optional ББК/УДК code.

Pure rules. A subject is a discipline or a field ("Экономика", "Социальные науки",
"English"); subjects nest, and topics hang under a subject (`taxonomy_topics`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.library.domain.taxonomy_errors import SubjectParentInvalidError

CODE_MAX = 40


@dataclass(slots=True)
class Subject:
    """A subject; `parent_id` None is a root, `archived_at` hides it from pickers."""

    id: UUID
    parent_id: UUID | None
    name: dict[str, str]
    slug: str
    position: int
    created_at: datetime
    updated_at: datetime
    code: str | None = None
    archived_at: datetime | None = None

    @property
    def archived(self) -> bool:
        """True when the subject is hidden from the catalogue."""
        return self.archived_at is not None


def clean_code(code: str | None) -> str | None:
    """The classification code ("ББК 65", "UDC 33") without stray spaces, or None."""
    text = " ".join((code or "").split())[:CODE_MAX]
    return text or None


def subject_descendants(subjects: Sequence[Subject], subject_id: UUID) -> set[UUID]:
    """Ids of everything below the subject (not the subject itself)."""
    children: dict[UUID, list[UUID]] = {}
    for subject in subjects:
        if subject.parent_id is not None:
            children.setdefault(subject.parent_id, []).append(subject.id)
    found: set[UUID] = set()
    stack = [subject_id]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def check_subject_parent(
    subjects: Sequence[Subject], *, parent_id: UUID, subject_id: UUID | None = None
) -> None:
    """The parent exists and the move keeps the tree acyclic."""
    if not any(s.id == parent_id for s in subjects):
        raise SubjectParentInvalidError(params={"parent_id": str(parent_id)})
    if subject_id is not None and (
        parent_id == subject_id
        or parent_id in subject_descendants(subjects, subject_id)
    ):
        raise SubjectParentInvalidError(params={"parent_id": str(parent_id)})
