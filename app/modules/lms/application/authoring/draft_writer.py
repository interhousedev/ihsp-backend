"""Preparing and applying step drafts: server IDs, hashes, file references."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.lms.domain.authoring.content_edit import (
    collect_ids,
    extract_file_ids,
)
from app.modules.lms.domain.authoring.entities import CourseStep, StepRevision
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.errors import (
    ContentInvalidError,
    FileMissingError,
)
from app.modules.lms.domain.authoring.hashing import canonical_json
from app.modules.lms.domain.step_content import (
    StepContent,
    assign_ids,
    canonical_hash,
)
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.shared.contracts.files import FilesApi

UNUSABLE_FILE_STATUSES = frozenset({"deleted", "rejected"})
MAX_CONTENT_BYTES = 1_000_000  # a step is 5-20 KB; this only stops abuse


@dataclass(frozen=True, slots=True)
class PreparedContent:
    """Step content ready to store: IDs assigned, hashed, files checked."""

    content: dict[str, Any]
    content_hash: str
    file_ids: list[UUID]

    @classmethod
    def from_revision(cls, revision: StepRevision) -> "PreparedContent":
        """Reuse the already validated content of an immutable revision."""
        return cls(
            content=dict(revision.content),
            content_hash=revision.content_hash,
            file_ids=list(revision.file_ids),
        )


class StepDraftWriter:
    """Validates step content and writes it to a step's working copy."""

    def __init__(self, files: FilesApi) -> None:
        """Store the files API used to check references."""
        self.files = files

    async def prepare(
        self, uow: AuthoringUnitOfWork, step: CourseStep, content: StepContent
    ) -> PreparedContent:
        """Assign server IDs, hash the content and check the files it references.

        Known IDs are those in the current draft and, only when the content brings
        an ID the draft does not have, in every revision of the step (LMS-23).
        """
        existing = collect_ids(step.draft)
        incoming = collect_ids(content.model_dump(mode="json"))
        if incoming - existing:
            existing |= await uow.revisions.known_ids(step.id)
        return await self._finish(content, existing)

    async def prepare_new(self, content: StepContent) -> PreparedContent:
        """Prepare the first content of a step that is being created.

        There are no known IDs yet, so every ID in the content is assigned by the
        server; otherwise the same checks as `prepare`.
        """
        return await self._finish(content, set())

    async def _finish(
        self, content: StepContent, existing: set[str]
    ) -> PreparedContent:
        try:
            assigned = assign_ids(content, existing)
        except ValueError as exc:
            raise ContentInvalidError(
                params={"reason": "duplicate-ids"}, support_details=str(exc)
            ) from exc
        data = assigned.model_dump(mode="json")
        if len(canonical_json(data).encode()) > MAX_CONTENT_BYTES:
            raise ContentInvalidError(
                params={"reason": "too-large", "max_bytes": MAX_CONTENT_BYTES}
            )
        file_ids = extract_file_ids(data)
        await self.require_files(file_ids)
        return PreparedContent(data, canonical_hash(assigned), file_ids)

    async def require_files(self, file_ids: list[UUID]) -> None:
        """Raise FileMissingError if a referenced file does not exist."""
        if not file_ids:
            return
        found = await self.files.get_many(file_ids)
        missing = [
            str(fid)
            for fid in file_ids
            if fid not in found or found[fid].status in UNUSABLE_FILE_STATUSES
        ]
        if missing:
            raise FileMissingError(params={"file_ids": missing})

    @staticmethod
    def apply(
        step: CourseStep,
        prepared: PreparedContent,
        *,
        by: UUID,
        via: StepVia,
        now: datetime,
    ) -> None:
        """Set the draft on the entity and bump its lock version."""
        step.draft = prepared.content
        step.draft_hash = prepared.content_hash
        step.file_ids = list(prepared.file_ids)
        step.draft_updated_by = by
        step.draft_updated_at = now
        step.draft_updated_via = via
        step.lock_version += 1
