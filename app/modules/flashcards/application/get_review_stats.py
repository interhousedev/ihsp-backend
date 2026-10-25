"""Use case: the heatmap and numbers of the deck overview (WEB-22, WEB-23)."""

from uuid import UUID

from app.modules.flashcards.application.views import DayCountView, ReviewStatsView
from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.modules.flashcards.domain.review_stats import compute_stats
from app.modules.flashcards.domain.study import day_end, day_start, study_day
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


class GetReviewStats:
    """Counts reviews per Tashkent day from the review log."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, *, owner_id: UUID, set_id: UUID | None = None, year: int | None = None
    ) -> ReviewStatsView:
        """Return the statistics of one set, or of all sets when `set_id` is None.

        `year` defaults to the current study year; a set of someone else is "not
        found".
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            if set_id is not None:
                flashcard_set = await uow.sets.get(set_id)
                if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                    raise FlashcardSetNotFoundError()
            counts = await uow.reviews.daily_counts(owner_id, set_id=set_id)
            today_ms = await uow.reviews.duration_ms_between(
                owner_id, set_id=set_id, start=day_start(now), end=day_end(now)
            )
        stats = compute_stats(
            counts,
            year=year or study_day(now).year,
            today=study_day(now),
            today_ms=today_ms,
        )
        return ReviewStatsView(
            year=stats.year,
            set_id=set_id,
            days=tuple(DayCountView(d.day, d.count) for d in stats.days),
            total_reviews=stats.total_reviews,
            days_studied=stats.days_studied,
            daily_average=stats.daily_average,
            days_learned_percent=stats.days_learned_percent,
            longest_streak=stats.longest_streak,
            current_streak=stats.current_streak,
            first_review_date=stats.first_review_date,
            today_count=stats.today_count,
            today_seconds=stats.today_seconds,
        )
