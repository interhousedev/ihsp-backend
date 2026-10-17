"""A teacher or student suggests a book; it lands in the librarian queue (LIB-2)."""

from typing import Any
from uuid import UUID

from app.modules.library.application.materials.upload_guard import UploadGuard
from app.modules.library.domain.moderation_entities import BookSuggestion
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id

TITLE_MAX = 255
URL_MAX = 2000
NOTE_MAX = 1000
SCHEMES = ("http://", "https://")


class CreateSuggestion:
    """Store a suggestion; librarians accept or decline it from the queue."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        files: FilesApi,
        academic: AcademicDirectory,
        guard: UploadGuard | None = None,
    ) -> None:
        """Initialize the use case (`guard` refuses users under an upload ban)."""
        self.guard = guard
        self.academic = academic
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files

    async def execute(
        self,
        actor: Actor,
        *,
        title: str,
        url: str | None,
        file_id: UUID | None,
        note: str | None,
        details: dict[str, Any] | None = None,
    ) -> BookSuggestion:
        """Check the fields and store the suggestion."""
        title = title.strip()
        url = (url or "").strip() or None
        note = (note or "").strip() or None
        if not title or len(title) > TITLE_MAX:
            raise ValidationFailedError(params={"field": "title"})
        if url is not None and (not url.startswith(SCHEMES) or len(url) > URL_MAX):
            raise ValidationFailedError(params={"field": "url"})
        if note is not None and len(note) > NOTE_MAX:
            raise ValidationFailedError(params={"field": "note"})
        await self._check_file(actor, file_id)
        if details is not None:
            await self._check_details(actor, details)
        suggestion = BookSuggestion(
            id=new_id(),
            user_id=actor.user_id,
            title=title,
            created_at=self.clock.now(),
            url=url,
            file_id=file_id,
            note=note,
            details=details,
        )
        async with self.uow_factory() as uow:
            if self.guard is not None:
                await self.guard.ensure_not_banned(uow, actor.user_id)
            await uow.moderation.add_suggestion(suggestion)
            await uow.commit()
        return suggestion

    async def _check_details(self, actor: Actor, details: dict[str, Any]) -> None:
        """Subjects, topics and the cover named in the form must exist and be usable."""
        subject_ids = {UUID(str(s["subject_id"])) for s in details.get("subjects", [])}
        topic_ids = {UUID(str(t["topic_id"])) for t in details.get("topics", [])}
        known = await self.academic.subject_names(list(subject_ids), "uz")
        if not subject_ids <= known.keys():
            raise ValidationFailedError(params={"field": "subjects"})
        if topic_ids:
            async with self.uow_factory() as uow:
                topics = await uow.taxonomy.topic_names(list(topic_ids))
            if not topic_ids <= topics.keys():
                raise ValidationFailedError(params={"field": "topics"})
        cover = details.get("cover_file_id")
        if cover is not None:
            await self._check_file(actor, UUID(str(cover)), field="cover_file_id")

    async def _check_file(
        self, actor: Actor, file_id: UUID | None, *, field: str = "file_id"
    ) -> None:
        if file_id is None:
            return
        ref = await self.files.get(file_id)
        if ref is None or ref.owner_id != actor.user_id:
            raise ValidationFailedError(params={"field": field})
