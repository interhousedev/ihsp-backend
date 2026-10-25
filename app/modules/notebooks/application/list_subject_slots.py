"""Use case: the subject notebook slots of a user, made or not yet (NB-AUTO)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.auto_targets import AutoTargets, SubjectSlot
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role


@dataclass(frozen=True, slots=True)
class SubjectNotebookSlot:
    """One subject (and group, for teachers) with its notebook if it exists."""

    subject_id: UUID
    subject_name: str
    group_id: UUID | None
    group_name: str | None
    notebook_id: UUID | None
    source_count: int


class ListSubjectSlots:
    """Lists a card for every subject the user has, whether its notebook exists.

    A student has one slot per subject of their lessons this term; a teacher, one per
    subject and group they teach. The notebook is made on first open (lazily), so a
    slot without one costs nothing. Notebooks of subjects the user no longer has
    this term are listed after the current slots, so none disappears.
    """

    def __init__(self, *, uow_factory: UowFactory, targets: AutoTargets) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.targets = targets

    async def execute(self, actor: Actor) -> list[SubjectNotebookSlot]:
        """Return the user's slots, grouped by subject name."""
        slots: list[SubjectSlot] = []
        if actor.has(Role.STUDENT):
            slots += await self.targets.student_slots(actor.user_id)
        if actor.has(Role.TEACHER):
            slots += await self.targets.teacher_slots(actor.user_id)
        async with self.uow_factory() as uow:
            made = await uow.notebooks.list_subject_auto(actor.user_id)
        by_key = {(n.subject_id, n.group_id): n for n in made}
        result = [
            self._slot(slot, by_key.pop((slot.subject_id, slot.group_id), None))
            for slot in slots
        ]
        for notebook in sorted(made, key=lambda n: n.title.casefold()):
            if (notebook.subject_id, notebook.group_id) in by_key:
                result.append(
                    SubjectNotebookSlot(
                        subject_id=notebook.subject_id,  # type: ignore[arg-type]
                        subject_name=notebook.title,
                        group_id=notebook.group_id,
                        group_name=None,
                        notebook_id=notebook.id,
                        source_count=notebook.source_count,
                    )
                )
        return result

    @staticmethod
    def _slot(slot: SubjectSlot, found: Notebook | None) -> SubjectNotebookSlot:
        return SubjectNotebookSlot(
            subject_id=slot.subject_id,
            subject_name=slot.subject_name,
            group_id=slot.group_id,
            group_name=slot.group_name,
            notebook_id=found.id if found else None,
            source_count=found.source_count if found else 0,
        )
