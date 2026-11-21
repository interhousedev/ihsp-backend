"""Short answers: a sealed text per supplemental prompt (`short_answer` prompts)."""

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.essay_categories import (
    SHORT_ANSWER_MAX_WORDS,
    ShortAnswer,
)
from app.modules.admission.domain.essays import word_count
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.base_error import ValidationFailedError


class EssayShortAnswers:
    """Read and write the student's short answers; the text is sealed at rest."""

    def __init__(self, uow_factory: UowFactory, gate: FlowGate) -> None:
        """Keep the unit of work factory and the owner gate."""
        self._uow = uow_factory
        self._gate = gate

    async def get(self, ctx: AdmissionContext, prompt_key: str) -> ShortAnswer:
        """The answer to a prompt; empty (0 words) when none was written."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            await self._prompt(uow, prompt_key)
            found = await uow.short_answers.get(ctx.user_id, prompt_key)
        return found or ShortAnswer(ctx.user_id, prompt_key, "", 0)

    async def put(
        self, ctx: AdmissionContext, prompt_key: str, text: str
    ) -> ShortAnswer:
        """Store the answer; at most 150 words, and the prompt's own word limit."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            ref_limit = await self._prompt(uow, prompt_key)
            words = word_count(text)
            cap = SHORT_ANSWER_MAX_WORDS
            if ref_limit is not None:
                cap = min(cap, ref_limit)
            if words > cap:
                raise ValidationFailedError(params={"field": "text", "max": cap})
            saved = await uow.short_answers.put(
                ShortAnswer(ctx.user_id, prompt_key, text, words)
            )
            await uow.commit()
        return saved

    @staticmethod
    async def _prompt(uow: AdmissionUnitOfWork, prompt_key: str) -> int | None:
        """The word limit (words only) of a catalog supplement; 404 otherwise."""
        for ref in await uow.prompt_catalog.all():
            if ref.key == prompt_key:
                return ref.word_limit if ref.limit_unit == "words" else None
        raise AdmissionNotFoundError()
