"""Finish an upload: verify the object in storage, sniff its type, queue processing."""

from uuid import UUID

from app.modules.files.application.access import require_owned
from app.modules.files.application.file_views import FileView, FileViewBuilder
from app.modules.files.application.process_hook import process_hook
from app.modules.files.domain.errors import StoredFileNotFoundError, UploadMissingError
from app.modules.files.domain.policy import SNIFF_BYTES, detected_matches, rule_for_name
from app.modules.files.domain.status import FileStatus, RejectReason
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.ports.content_sniffer import ContentSniffer
from app.modules.files.ports.storage import ObjectInfo, ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)


class CompleteUpload:
    """Check size, checksum and real type of the uploaded object (FILE-2)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        storage: ObjectStorage,
        sniffer: ContentSniffer,
        views: FileViewBuilder,
        clock: Clock,
        kicker: TaskKicker,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._sniffer = sniffer
        self._views = views
        self._clock = clock
        self._kicker = kicker

    async def execute(self, actor: Actor, file_id: UUID) -> FileView:
        """Accept the upload (processing) or reject it; repeated calls are safe."""
        async with self._uow_factory() as uow:
            file = require_owned(await uow.files.get(file_id), actor)
        if file.status != FileStatus.PENDING:
            return await self._views.build_one(file)
        reason = await self._verify(file)
        file = await self._finish(file_id, reason)
        if file.status == FileStatus.REJECTED:
            await self._storage.delete_many(file.storage_keys())
        return await self._views.build_one(file)

    async def _verify(self, file: StoredFile) -> RejectReason | None:
        """Return why the object must be rejected, or None when it is fine."""
        info = await self._storage.head(file.key)
        if info is None:
            raise UploadMissingError(params={"file_id": str(file.id)})
        wrong = self._wrong_bytes(file, info)
        if wrong is not None:
            return wrong
        head = await self._storage.read_range(
            file.key, 0, min(file.byte_size, SNIFF_BYTES) - 1
        )
        detected = await self._sniffer.sniff(head)
        rule = rule_for_name(file.name)
        if rule is None or not detected_matches(rule, detected, head):
            log.info("upload_type_mismatch", file_id=str(file.id), detected=detected)
            return RejectReason.TYPE_MISMATCH
        return None

    @staticmethod
    def _wrong_bytes(file: StoredFile, info: ObjectInfo) -> RejectReason | None:
        """Compare the object's size and checksum with what was declared."""
        if info.size != file.byte_size:
            return RejectReason.CHECKSUM_MISMATCH
        if info.checksum_sha256 and info.checksum_sha256 != file.checksum:
            return RejectReason.CHECKSUM_MISMATCH
        return None

    async def _finish(self, file_id: UUID, reason: RejectReason | None) -> StoredFile:
        """Save the verdict; when two calls race, the first one wins."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
            if file is None:
                raise StoredFileNotFoundError()
            if file.status != FileStatus.PENDING:
                return file
            if reason is None:
                rule = rule_for_name(file.name)
                canonical = rule.canonical if rule else file.content_type
                file.mark_processing(canonical, now)
                uow.after_commit(process_hook(self._kicker, file.id))
            else:
                file.reject(reason, now)
            await uow.files.save(file)
            await uow.commit()
        return file
