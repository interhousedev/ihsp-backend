"""Warn students 7 days before their term's files are deleted (FILE-6)."""

from app.modules.files.domain.policy import expiry_date, in_warning_window
from app.modules.files.ports.term_resolver import TermResolver
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.clock import Clock, local_today
from app.shared.notifications import NotificationDraft, NotificationType


class WarnExpiring:
    """One ``files_expiring`` notification per owner and term, deduplicated."""

    def __init__(
        self, *, uow_factory: UowFactory, terms: TermResolver, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._terms = terms
        self._clock = clock

    async def execute(self) -> int:
        """Queue notifications for terms inside the warning window; return how many."""
        today = local_today(self._clock)
        async with self._uow_factory() as uow:
            term_ids = await uow.files.student_term_ids()
        queued = 0
        for term_id in term_ids:
            end = await self._terms.term_end(term_id)
            if end is None or not in_warning_window(end, today):
                continue
            async with self._uow_factory() as uow:
                owners = await uow.files.term_owner_counts(term_id)
                uow.notify(
                    *(
                        NotificationDraft(
                            user_id=owner,
                            type=NotificationType.FILES_EXPIRING,
                            payload={
                                "term_id": str(term_id),
                                "expires_on": expiry_date(end).isoformat(),
                                "files_count": count,
                            },
                            dedupe_key=f"files-expiring:{term_id}:{owner}",
                        )
                        for owner, count in owners
                    )
                )
                await uow.commit()
            queued += len(owners)
        return queued
