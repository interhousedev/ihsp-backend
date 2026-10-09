"""Use case: the student asks the notebook a question (NB-6, § 3.3.1)."""

from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing
from uuid import UUID

from app.modules.notebooks.application.answering import AnswerPipeline, AnswerRequest
from app.modules.notebooks.application.views import StreamEvent, TurnView
from app.modules.notebooks.domain.entities import AnchorPassages, AnchorText
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor


class AskNotebook:
    """Answers a question from the selected sources, with citations."""

    def __init__(self, core: NotebooksCore) -> None:
        """Build the answer pipeline over the shared services."""
        self.pipeline = AnswerPipeline(core)

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        text: str,
        source_ids: Sequence[UUID] | None = None,
        anchor: AnchorPassages | AnchorText | None = None,
        web_search: bool = False,
    ) -> TurnView:
        """Answer in one piece and store both messages.

        Args:
            actor: The student; the notebook must be theirs.
            notebook_id: The notebook.
            text: The question, 1 to 4 000 characters after trimming.
            source_ids: Sources to ask; the persisted selection when ``None``.
            anchor: Pinned passages or a selected text.
            web_search: Also search the web for this question (spends one of the
                day's searches); the answer cites the pages as web chips.

        Returns:
            Both messages, the fresh usage and a proposed Studio output, if any.

        Raises:
            NotebookNotFoundError: Not the student's notebook.
            InvalidOptionsError: The question is empty or too long.
            RateLimitedError: More than 10 questions in a minute.
            BusyError: Another question of the student is running here.
            NoSourcesSelectedError: No usable source is selected.
            LimitReachedError: The budget cannot pay for the question.
            WebSearchDisabledError: `web_search` while the feature is off.
            WebSearchQuotaError: No searches are left today.
            WebSearchUnavailableError: The search failed (nothing is stored).
            AiProviderError: The model failed (nothing is stored).
        """
        clean = await self.pipeline.admit_question(actor.user_id, notebook_id, text)
        request = AnswerRequest(
            actor.user_id, notebook_id, clean, source_ids, anchor, web_search, actor
        )
        return await self.pipeline.answer(request)

    async def stream(
        self,
        actor: Actor,
        notebook_id: UUID,
        text: str,
        source_ids: Sequence[UUID] | None = None,
        anchor: AnchorPassages | AnchorText | None = None,
        web_search: bool = False,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Answer as server-sent events (see `AnswerPipeline.stream`).

        Errors raised before the first event (the same as in `execute`) store
        nothing; the first event is ``message``, then ``web`` when the question
        searched the web.
        """
        clean = await self.pipeline.admit_question(actor.user_id, notebook_id, text)
        request = AnswerRequest(
            actor.user_id, notebook_id, clean, source_ids, anchor, web_search, actor
        )
        async with aclosing(self.pipeline.stream(request)) as events:
            async for event in events:
                yield event
