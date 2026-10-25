"""SQL unit of work of the flashcards module."""

from app.modules.flashcards.infrastructure.repositories.card_repository import (
    SqlFlashcardRepository,
)
from app.modules.flashcards.infrastructure.repositories.review_log_repository import (
    SqlReviewLogRepository,
)
from app.modules.flashcards.infrastructure.repositories.set_repository import (
    SqlFlashcardSetRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlFlashcardsUnitOfWork(SqlUnitOfWork):
    """One transaction over flash card sets, cards and the review log."""

    sets: SqlFlashcardSetRepository
    cards: SqlFlashcardRepository
    reviews: SqlReviewLogRepository

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.sets = SqlFlashcardSetRepository(self.session)
        self.cards = SqlFlashcardRepository(self.session)
        self.reviews = SqlReviewLogRepository(self.session)
