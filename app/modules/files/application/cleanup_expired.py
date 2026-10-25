"""Delete expired files: student files of ended terms and files past expires_at."""

from uuid import UUID

from app.modules.files.domain.policy import is_term_expired
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.term_resolver import TermResolver
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.clock import Clock, local_today

import structlog

log = structlog.get_logger(__name__)

BATCH_FILES = 500  # two objects per file: 1000 keys per DeleteObjects call


class CleanupExpired:
    """UF-SYS-07 and UF-SYS-08 (files part), run daily."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        storage: ObjectStorage,
        terms: TermResolver,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._terms = terms
        self._clock = clock

    async def execute(self) -> int:
        """Delete objects and sidecars in batches; return the number of files."""
        expired_terms = await self._expired_terms()
        now = self._clock.now()
        total = 0
        while True:
            async with self._uow_factory() as uow:
                batch = await uow.files.list_expired(
                    expired_term_ids=expired_terms, now=now, limit=BATCH_FILES
                )
                if not batch:
                    break
                keys = [key for file in batch for key in file.storage_keys()]
                await self._storage.delete_many(keys)
                await uow.files.mark_deleted([file.id for file in batch], now)
                await uow.commit()
            total += len(batch)
        log.info("files_cleanup_done", deleted=total, terms=len(expired_terms))
        return total

    async def _expired_terms(self) -> list[UUID]:
        """Terms whose files are past their expiry day."""
        today = local_today(self._clock)
        async with self._uow_factory() as uow:
            term_ids = await uow.files.student_term_ids()
        expired: list[UUID] = []
        for term_id in term_ids:
            end = await self._terms.term_end(term_id)
            if end is not None and is_term_expired(end, today):
                expired.append(term_id)
        return expired
