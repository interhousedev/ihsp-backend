"""Aggregate library statistics for librarians and Administration (LIB-16)."""

from datetime import UTC, date, datetime, time, timedelta

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.views import (
    LibraryStatsView,
    SearchMissView,
    TopItemView,
    UploadDayView,
)
from app.modules.library.application.views import SubjectView
from app.modules.library.domain.taxonomy_stats import days_between, resolve_range
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.stats_repository import StatsCounters
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory

TOP_ITEMS = 10
NO_RESULT_LIMIT = 20


def _start_of(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


class GetLibraryStats:
    """`GET /v1/manage/library/stats?from&to`: numbers, never individuals."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
        academic: AcademicDirectory,
        cards: CardBuilder,
        counters: StatsCounters,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.academic = academic
        self.cards = cards
        self.counters = counters

    async def execute(
        self,
        actor: Actor,
        *,
        start: date | None = None,
        end: date | None = None,
        accept_language: str | None = None,
    ) -> LibraryStatsView:
        """The figures of the window (the last 30 days by default)."""
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        first, last = resolve_range(self.clock.now().date(), start, end)
        since, until = _start_of(first), _start_of(last + timedelta(days=1))
        locale = await resolve_locale(self.identity, actor, accept_language)
        misses = await self._misses(first, last)
        async with self.uow_factory() as uow:
            opens, readers = await uow.stats.totals(first, last)
            top = await uow.stats.top_items(first, last, TOP_ITEMS)
            found = await uow.items.get_many([item_id for item_id, _ in top])
            ordered = [(found[i], n) for i, n in top if i in found]
            cards = await self.cards.build(
                uow, [item for item, _ in ordered], viewer=actor, locale=locale
            )
            statuses = await uow.stats.item_status_counts()
            reasons = await uow.stats.report_counts(since, until)
            uploads = await uow.stats.uploads_by_day(since, until)
            queue = await uow.moderation.queue_age_stats(self.clock.now())
            covered = await uow.stats.subject_ids_with_materials()
        subjects = await self.academic.list_subjects(locale)
        return LibraryStatsView(
            opens=opens,
            readers=readers,
            queue=queue,
            uploads_by_day=tuple(
                UploadDayView(day=day, count=uploads.get(day, 0))
                for day in days_between(first, last)
            ),
            searches_without_results=misses,
            top_items=tuple(
                TopItemView(item=card, opens=n)
                for card, (_, n) in zip(cards, ordered, strict=True)
            ),
            items_by_status=statuses,
            reports_by_reason=reasons,
            subjects_without_materials=tuple(
                SubjectView(id=s.id, name=s.name)
                for s in subjects
                if s.id not in covered
            ),
        )

    async def _misses(self, first: date, last: date) -> tuple[SearchMissView, ...]:
        """Searches that found nothing, summed over the window (last 7 days at most)."""
        totals: dict[str, int] = {}
        window = days_between(max(first, last - timedelta(days=6)), last)
        for day in window:
            for query, count in (
                await self.counters.no_results(day, NO_RESULT_LIMIT)
            ).items():
                totals[query] = totals.get(query, 0) + count
        top = sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
        return tuple(SearchMissView(q=q, count=n) for q, n in top[:NO_RESULT_LIMIT])
