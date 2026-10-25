"""Start an upload: validate, check the quota atomically, return a presigned PUT."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.files.application.file_views import FileView, FileViewBuilder
from app.modules.files.domain.errors import QuotaExceededError, TypeNotAllowedError
from app.modules.files.domain.policy import (
    LIBRARY_PURPOSES,
    PRESIGN_PUT_SECONDS,
    VIDEO_PURPOSES,
    FilesLimits,
    check_checksum,
    check_declared,
    check_purpose_extension,
    check_size,
    check_upload_role,
    key_extension,
    key_for,
    month_label,
    normalize_name,
    scope_for_purpose,
)
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.ports.storage import ObjectStorage, PresignedUpload
from app.modules.files.ports.term_resolver import TermResolver
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.ids import new_id

UPLOAD_PURPOSES = (
    frozenset({FilePurpose.AI_UPLOAD, FilePurpose.LINK, FilePurpose.FEEDBACK})
    | LIBRARY_PURPOSES
    | VIDEO_PURPOSES
)


@dataclass(frozen=True, slots=True)
class UploadTicket:
    """The new pending file and the request the client must make to storage."""

    view: FileView
    upload: PresignedUpload


class RequestUpload:
    """Create a pending file row and a presigned PUT URL (FILE-2, FILE-5)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        storage: ObjectStorage,
        terms: TermResolver,
        views: FileViewBuilder,
        clock: Clock,
        limits: FilesLimits,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._terms = terms
        self._views = views
        self._clock = clock
        self._limits = limits

    async def execute(
        self,
        actor: Actor,
        *,
        name: str,
        size: int,
        content_type: str,
        sha256_b64: str,
        purpose: FilePurpose,
    ) -> UploadTicket:
        """Validate the request and reserve the quota; return the upload ticket."""
        if purpose not in UPLOAD_PURPOSES:
            raise TypeNotAllowedError(params={"purpose": purpose.value})
        check_upload_role(purpose, actor)
        clean = normalize_name(name)
        check_purpose_extension(purpose, clean)
        _, signed_type = check_declared(clean, content_type)
        scope = scope_for_purpose(purpose, actor)
        check_size(size, self._limits.max_bytes_for_purpose(purpose, scope))
        checksum = check_checksum(sha256_b64)
        term_id = await self._term_for(scope)
        now = self._clock.now()
        file_id = new_id()
        label = str(term_id) if term_id else month_label(now)
        key = key_for(scope, label, file_id, key_extension(clean))
        upload = await self._storage.presign_put(
            key,
            content_type=signed_type,
            content_length=size,
            sha256_b64=checksum,
            expires=PRESIGN_PUT_SECONDS,
        )
        file = StoredFile(
            id=file_id,
            owner_id=actor.user_id,
            scope=scope,
            purpose=purpose,
            key=key,
            name=clean,
            content_type=signed_type,
            byte_size=size,
            checksum=checksum,
            status=FileStatus.PENDING,
            created_at=now,
            updated_at=now,
            term_id=term_id,
        )
        await self._reserve(file, self._limits.quota_for_actor(scope, actor))
        return UploadTicket(view=await self._views.build_one(file), upload=upload)

    async def _term_for(self, scope: FileScope) -> UUID | None:
        """Students' files belong to the current term (or the next one)."""
        if scope != FileScope.STUDENT:
            return None
        return await self._terms.current_term_id(local_today(self._clock))

    async def _reserve(self, file: StoredFile, quota: int | None) -> None:
        """Check the quota under the owner's advisory lock and insert the row."""
        async with self._uow_factory() as uow:
            await uow.files.lock_owner(file.owner_id)
            used = await uow.files.used_bytes(file.owner_id, file.scope, file.term_id)
            if quota is not None and used + file.byte_size > quota:
                raise QuotaExceededError(
                    params={
                        "used_bytes": used,
                        "quota_bytes": quota,
                        "size": file.byte_size,
                    }
                )
            await uow.files.add(file)
            await uow.commit()
