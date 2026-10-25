"""Use case: answer the last question again (NB-7, § 3.3.6)."""

from collections.abc import AsyncGenerator
from contextlib import aclosing
from uuid import UUID

from app.modules.notebooks.application.answering import AnswerPipeline, AnswerRequest
from app.modules.notebooks.application.views import StreamEvent, TurnView
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor


class RegenerateChat:
    """Replaces the last answer; allowed only for the last turn."""

    def __init__(self, core: NotebooksCore) -> None:
        """Build the answer pipeline over the shared services."""
        self.pipeline = AnswerPipeline(core)

    async def execute(self, actor: Actor, notebook_id: UUID) -> TurnView:
        """Answer the last question again with the sources and anchor it had.

        The old answer is deleted when the new one is stored, which takes its
        place (same ``seq``).

        Raises:
            NotebookNotFoundError: Not the student's notebook.
            InvalidOptionsError: The thread does not end with a question and its
                answer (``params.reason == "nothing-to-regenerate"``).
            RateLimitedError: More than 10 questions in a minute.
            BusyError: Another question of the student is running here.
            NoSourcesSelectedError: None of the question's sources is usable now.
            LimitReachedError: The budget cannot pay for the answer.
            AiProviderError: The model failed (the old answer stays).
        """
        await self.pipeline.admit_regeneration(actor.user_id, notebook_id)
        return await self.pipeline.answer(AnswerRequest(actor.user_id, notebook_id))

    async def stream(
        self, actor: Actor, notebook_id: UUID
    ) -> AsyncGenerator[StreamEvent, None]:
        """Regenerate as server-sent events; the first event is ``message``."""
        await self.pipeline.admit_regeneration(actor.user_id, notebook_id)
        request = AnswerRequest(actor.user_id, notebook_id)
        async with aclosing(self.pipeline.stream(request)) as events:
            async for event in events:
                yield event
