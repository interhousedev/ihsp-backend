"""Builds the TurnResultView returned by the turn use cases."""

from app.modules.ai.application.budget import BudgetService
from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.continue_turn import TurnProgress
from app.modules.ai.application.views import TurnResultView
from app.modules.ai.domain.chat import ChatMessage
from app.shared.actor import Actor
from app.shared.clock import Clock


class TurnResults:
    """Localizes a finished turn and attaches the remaining budget."""

    def __init__(self, views: ChatViews, budget: BudgetService, clock: Clock) -> None:
        """Store the collaborators."""
        self.views = views
        self.budget = budget
        self.clock = clock

    async def build(
        self, actor: Actor, locale: str, progress: TurnProgress
    ) -> TurnResultView:
        """Return the result; changed messages are deduplicated and ordered by seq."""
        latest: dict[int, ChatMessage] = {m.seq: m for m in progress.changed}
        now = self.clock.now()
        return TurnResultView(
            chat=self.views.chat_item(progress.chat),
            new_messages=[
                self.views.message(latest[seq], locale, now) for seq in sorted(latest)
            ],
            status=progress.status,
            usage=await self.budget.usage_for(actor, progress.chat.assistant),
        )
