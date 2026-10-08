"""Builds the views of sets and study screens, with today's counters."""

from collections.abc import Sequence

from app.modules.flashcards.application.views import (
    CardView,
    CountsView,
    IntervalsView,
    SetDetailView,
    SetItemView,
    StudyCardView,
    StudyNextView,
)
from app.modules.flashcards.domain.flashcard import Flashcard
from app.modules.flashcards.domain.flashcard_set import FlashcardSet, SetCounts
from app.modules.flashcards.domain.intervals import format_interval
from app.modules.flashcards.domain.study import (
    DailyUsage,
    day_end,
    is_due_today,
    new_today,
    plan_study,
    study_day,
)
from app.modules.flashcards.ports.daily_counters import DailyCounters
from app.shared.clock import Clock
from app.shared.srs import CardState, Rating, preview


def card_view(card: Flashcard) -> CardView:
    """Return the view of one card."""
    return CardView(
        id=card.id,
        set_id=card.set_id,
        position=card.position,
        front=card.front,
        back=card.back,
        state=card.state.value,
        due_at=card.due_at,
    )


class SetViews:
    """Turns entities into views; reads today's counters for `new_today`."""

    def __init__(self, *, clock: Clock, counters: DailyCounters) -> None:
        """Store the collaborators."""
        self.clock = clock
        self.counters = counters

    async def usage(self, flashcard_set: FlashcardSet) -> DailyUsage:
        """Return what the owner already studied in the set today."""
        day = study_day(self.clock.now())
        return await self.counters.usage(flashcard_set.owner_id, flashcard_set.id, day)

    async def item(self, flashcard_set: FlashcardSet, counts: SetCounts) -> SetItemView:
        """Return the list item: `due_today` and `new_today` from the counts."""
        usage = await self.usage(flashcard_set)
        return SetItemView(
            id=flashcard_set.id,
            title=flashcard_set.title,
            description=flashcard_set.description,
            source=flashcard_set.source.value,
            card_count=flashcard_set.card_count,
            due_today=counts.due,
            new_today=new_today(counts.new, flashcard_set.new_per_day, usage.new),
        )

    async def detail(
        self, flashcard_set: FlashcardSet, cards: Sequence[Flashcard]
    ) -> SetDetailView:
        """Return the set with its cards, counting `due_today` and `new_today`."""
        end_of_day = day_end(self.clock.now())
        counts = SetCounts(
            new=sum(1 for card in cards if card.state is CardState.NEW),
            due=sum(1 for card in cards if is_due_today(card, end_of_day)),
        )
        item = await self.item(flashcard_set, counts)
        return SetDetailView(
            id=item.id,
            title=item.title,
            description=item.description,
            source=item.source,
            card_count=item.card_count,
            due_today=item.due_today,
            new_today=item.new_today,
            new_per_day=flashcard_set.new_per_day,
            reviews_per_day=flashcard_set.reviews_per_day,
            cards=tuple(card_view(card) for card in cards),
        )

    async def study(
        self, flashcard_set: FlashcardSet, cards: Sequence[Flashcard]
    ) -> StudyNextView:
        """Return the next card to study with the button labels and queue sizes."""
        now = self.clock.now()
        plan = plan_study(
            cards,
            new_per_day=flashcard_set.new_per_day,
            reviews_per_day=flashcard_set.reviews_per_day,
            usage=await self.usage(flashcard_set),
            now=now,
        )
        counts = CountsView(
            learning=plan.counts.learning,
            review=plan.counts.review,
            new=plan.counts.new,
        )
        card = plan.card
        if card is None:
            return StudyNextView(flashcard_set.id, None, None, counts, True)
        labels = {r: format_interval(d) for r, d in preview(card.srs, now).items()}
        return StudyNextView(
            set_id=flashcard_set.id,
            card=StudyCardView(card.id, card.front, card.back, card.state.value),
            intervals=IntervalsView(
                again=labels[Rating.AGAIN],
                hard=labels[Rating.HARD],
                medium=labels[Rating.MEDIUM],
                easy=labels[Rating.EASY],
            ),
            counts=counts,
            done_for_today=False,
        )
