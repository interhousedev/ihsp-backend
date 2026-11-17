"""Use cases of memory notes: only the student reads, writes and deletes them."""

from collections.abc import Callable
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.memory_notes import (
    MemoryNote,
    NoteSource,
    check_room,
    clean_content,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork
from app.shared.clock import Clock
from app.shared.ids import new_id

UowFactory = Callable[[], AdmissionUnitOfWork]


class MemoryNoteService:
    """The caller's own memory notes; another user's note is not found."""

    def __init__(
        self, uow_factory: UowFactory, access: AccessPolicy, clock: Clock
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock

    async def list(self, ctx: AdmissionContext) -> list[MemoryNote]:
        """Return the caller's notes, newest first."""
        await self._require_owner(ctx)
        async with self._uow() as uow:
            return await uow.memory_notes.list_for(ctx.user_id)

    async def add(
        self, ctx: AdmissionContext, content: str, source: NoteSource
    ) -> MemoryNote:
        """Save a note for the caller."""
        await self._require_owner(ctx)
        text = clean_content(content)
        async with self._uow() as uow:
            check_room(await uow.memory_notes.count_for(ctx.user_id))
            note = MemoryNote(
                id=new_id(),
                student_id=ctx.user_id,
                content=text,
                source=source,
                created_at=self._clock.now(),
            )
            await uow.memory_notes.add(note)
            self._audit(uow, ctx, "memory_note.created", note.id, source)
            await uow.commit()
        return note

    async def delete(
        self, ctx: AdmissionContext, note_id: UUID, source: NoteSource = "app"
    ) -> None:
        """Delete one of the caller's notes."""
        await self._require_owner(ctx)
        async with self._uow() as uow:
            note = await uow.memory_notes.get(note_id)
            if note is None or note.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            await uow.memory_notes.delete(note_id)
            self._audit(uow, ctx, "memory_note.deleted", note_id, source)
            await uow.commit()

    async def _require_owner(self, ctx: AdmissionContext) -> None:
        await self._access.require(ctx, ctx.user_id, Permission.PROFILE_READ)

    @staticmethod
    def _audit(
        uow: AdmissionUnitOfWork,
        ctx: AdmissionContext,
        action: str,
        note_id: UUID,
        source: NoteSource,
    ) -> None:
        uow.access.audit(
            AuditEvent(
                action=action,
                actor_id=ctx.user_id,
                student_id=ctx.user_id,
                object_type="memory_note",
                object_id=note_id,
                meta={"source": source},
            )
        )
