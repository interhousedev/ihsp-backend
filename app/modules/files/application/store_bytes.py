"""Store bytes uploaded through the server (Telegram bot, inbound mail, LMS)."""

import base64
import hashlib
from datetime import datetime, timedelta
from uuid import UUID

from app.modules.files.application.process_hook import process_hook
from app.modules.files.domain.errors import QuotaExceededError, TypeNotAllowedError
from app.modules.files.domain.policy import (
    SNIFF_BYTES,
    FilesLimits,
    check_scope_purpose,
    check_size,
    detected_matches,
    key_extension,
    key_for,
    month_label,
    normalize_name,
    rule_for_name,
)
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.ports.content_sniffer import ContentSniffer
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.term_resolver import TermResolver
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.clock import Clock, local_today
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker


def _expires_at(scope: FileScope, now: datetime, days: int | None) -> datetime | None:
    """Library files are kept for good (FILE-6 does not apply to them)."""
    if days is None or scope == FileScope.LIBRARY:
        return None
    return now + timedelta(days=days)


class StoreBytes:
    """Validate like an upload (except for mail files) and write the object."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        storage: ObjectStorage,
        sniffer: ContentSniffer,
        terms: TermResolver,
        clock: Clock,
        kicker: TaskKicker,
        limits: FilesLimits,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._sniffer = sniffer
        self._terms = terms
        self._clock = clock
        self._kicker = kicker
        self._limits = limits

    async def execute(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        data: bytes,
        expires_days: int | None = None,
    ) -> StoredFile:
        """Write the object and its row; text extraction runs in the background.

        Library files never expire and have no quota here: the library module checks
        who may upload what, and ``expires_days`` is ignored for them.
        """
        check_scope_purpose(scope, purpose)
        clean = normalize_name(name)
        content_type = await self._check_content(scope, purpose, clean, data)
        now = self._clock.now()
        term_id = await self._term_for(scope)
        file_id = new_id()
        label = str(term_id) if term_id else month_label(now)
        file = StoredFile(
            id=file_id,
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            key=key_for(scope, label, file_id, key_extension(clean)),
            name=clean,
            content_type=content_type,
            byte_size=len(data),
            checksum=base64.b64encode(hashlib.sha256(data).digest()).decode(),
            status=self._first_status(purpose),
            created_at=now,
            updated_at=now,
            term_id=term_id,
            expires_at=_expires_at(scope, now, expires_days),
        )
        await self._write(file, data)
        return file

    @staticmethod
    def _first_status(purpose: FilePurpose) -> FileStatus:
        """Mail files are ready at once; others wait for text extraction."""
        return (
            FileStatus.READY if purpose == FilePurpose.MAIL else FileStatus.PROCESSING
        )

    async def _check_content(
        self, scope: FileScope, purpose: FilePurpose, name: str, data: bytes
    ) -> str:
        """Return the content type; for non-mail files refuse unlisted types."""
        head = data[:SNIFF_BYTES]
        detected = await self._sniffer.sniff(head) if head else "application/x-empty"
        if purpose == FilePurpose.MAIL:
            return detected
        check_size(len(data), self._limits.max_bytes_for(scope))
        rule = rule_for_name(name)
        if rule is None or not detected_matches(rule, detected, head):
            raise TypeNotAllowedError(params={"content_type": detected})
        return rule.canonical

    async def _term_for(self, scope: FileScope) -> UUID | None:
        """Student files belong to the current (or next) term."""
        if scope != FileScope.STUDENT:
            return None
        return await self._terms.current_term_id(local_today(self._clock))

    async def _write(self, file: StoredFile, data: bytes) -> None:
        """Check the quota under the advisory lock, write the object, insert the row."""
        quota = self._limits.quota_for(file.scope)
        async with self._uow_factory() as uow:
            if quota is not None:
                await uow.files.lock_owner(file.owner_id)
                used = await uow.files.used_bytes(
                    file.owner_id, file.scope, file.term_id
                )
                if used + file.byte_size > quota:
                    raise QuotaExceededError(
                        params={
                            "used_bytes": used,
                            "quota_bytes": quota,
                            "size": file.byte_size,
                        }
                    )
            await self._storage.put(file.key, data, file.content_type)
            await uow.files.add(file)
            if file.status == FileStatus.PROCESSING:
                uow.after_commit(process_hook(self._kicker, file.id))
            await uow.commit()
