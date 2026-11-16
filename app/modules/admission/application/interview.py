"""AI interview about one item (§9.1): up to three rounds, then a proposal."""

from dataclasses import dataclass, replace
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review import (
    ItemInput,
    caps_of,
    fix_rewrite,
    owned_item,
)
from app.modules.admission.application.review_checks import (
    delimit,
    looks_injected,
    nfc,
    plain,
)
from app.modules.admission.application.review_prompts import render_prompt
from app.modules.admission.application.review_schema import (
    INTERVIEW_SCHEMA,
    INTERVIEW_SCHEMA_NAME,
    MAX_OPTIONS,
    MAX_QUESTIONS,
    AiInterview,
)
from app.modules.admission.domain.errors import InvalidAnswerError, WordsNotSetError
from app.modules.admission.ports.ai import PromptSource, StructuredAi
from app.modules.admission.ports.items import InterviewRound, ProfileWordsRef
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError
from app.shared.ids import new_id

from pydantic import ValidationError

MAX_ROUNDS: Final = 3
ANSWER_MAX: Final = 500
INTERVIEW_TOKENS: Final = 1500


@dataclass(frozen=True, slots=True)
class InterviewState:
    """The rounds so far; `proposal` is set once the interview is ready."""

    item_id: UUID
    rounds: list[InterviewRound]
    ready: bool
    proposal: dict[str, Any] | None
    safeguarding: bool = False


def _state(item_id: UUID, rounds: list[InterviewRound]) -> InterviewState:
    last = rounds[-1].questions if rounds else {}
    return InterviewState(
        item_id,
        rounds,
        bool(last.get("ready")),
        last.get("proposal"),
        bool(last.get("safeguarding")),
    )


def _clean_answers(round_: InterviewRound, answers: dict[str, str]) -> dict[str, str]:
    """Keep answers to the round's questions, as plain text within the cap."""
    asked = {str(i) for i in range(len(round_.questions.get("questions", [])))}
    clean: dict[str, str] = {}
    for key, value in answers.items():
        if key not in asked:
            raise InvalidAnswerError(params={"question": key})
        text = nfc(plain(value)).strip()
        if len(text) > ANSWER_MAX:
            raise InvalidAnswerError(params={"question": key})
        if text:
            clean[key] = text
    return clean


def _transcript(rounds: list[InterviewRound]) -> str:
    """Return the earlier questions and answers as untrusted data."""
    lines: list[str] = []
    for r in rounds:
        for i, q in enumerate(r.questions.get("questions", [])):
            answer = r.answers.get(str(i), "")
            q_text = str(q.get("question", "")).replace("<", "‹").replace(">", "›")
            a_text = answer.replace("<", "‹").replace(">", "›")
            lines.append(f"round {r.round} q{i}: {q_text}\nanswer: {a_text}")
    return "<answers>\n" + "\n".join(lines) + "\n</answers>"


class ItemInterviewService:
    """Run the interview rounds of an item."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        prompts: PromptSource,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._prompts = prompts

    async def get(self, ctx: AdmissionContext, item_id: UUID) -> InterviewState:
        """Return the rounds so far."""
        async with self._uow() as uow:
            await owned_item(self._access, uow, ctx, item_id)
            return _state(item_id, await uow.items.interviews(item_id))

    async def step(
        self,
        ctx: AdmissionContext,
        item_id: UUID,
        answers: dict[str, str],
        locale: str,
        *,
        restart: bool = False,
    ) -> InterviewState:
        """Store answers to the last round and ask the next one (idempotent)."""
        async with self._uow() as uow:
            item = await owned_item(self._access, uow, ctx, item_id)
            if restart:
                await uow.items.clear_interviews(item_id)
            rounds = await uow.items.interviews(item_id)
            state = _state(item_id, rounds)
            if state.ready or state.safeguarding:
                await uow.commit()
                return state
            if rounds:
                last = rounds[-1]
                clean = _clean_answers(last, answers)
                if not clean and not last.answers:
                    await uow.commit()
                    return state
                if clean:
                    last = replace(last, answers={**last.answers, **clean})
                    await uow.items.update_round(last.id, answers=last.answers)
                    rounds[-1] = last
            metrics = (await uow.items.metrics_for([item.id])).get(item.id, [])
            words = await uow.items.words(item.student_id)
            await uow.commit()
        if words is None or not words.words:
            raise WordsNotSetError()
        final = len(rounds) >= MAX_ROUNDS
        number = len(rounds) if final else len(rounds) + 1
        parsed = await self._ask(
            ItemInput(item, metrics, words), rounds, number, locale, final=final
        )
        return await self._store(
            item, metrics, words, rounds, number, parsed, final, locale
        )

    async def _ask(
        self,
        data: ItemInput,
        rounds: list[InterviewRound],
        number: int,
        locale: str,
        *,
        final: bool,
    ) -> AiInterview:
        strict = looks_injected(data.item)
        system = await render_prompt(
            self._prompts,
            AiTask.ADMIT_ITEM_INTERVIEW,
            "system",
            locale,
            kind=data.item.kind,
            round=number,
            max_rounds=MAX_ROUNDS,
            **caps_of(data.item.kind),
        )
        if final:
            system += (
                "\nThis is the end of the interview: set ready_for_review to true, "
                "ask no questions and give the proposal."
            )
        user = (
            delimit(data.item, data.metrics, strict=strict) + "\n" + _transcript(rounds)
        )
        raw, _ = await self._ai.json(
            task=AiTask.ADMIT_ITEM_INTERVIEW,
            system=system,
            user=user,
            schema_name=INTERVIEW_SCHEMA_NAME,
            schema=INTERVIEW_SCHEMA,
            max_tokens=INTERVIEW_TOKENS,
        )
        try:
            return AiInterview.model_validate(raw)
        except ValidationError as exc:
            raise AiInvalidOutputError(support_details=str(exc)) from exc

    async def _store(
        self,
        item: Any,
        metrics: list[Any],
        words: ProfileWordsRef,
        rounds: list[InterviewRound],
        number: int,
        parsed: AiInterview,
        final: bool,
        locale: str,
    ) -> InterviewState:
        ready = final or parsed.ready_for_review or not parsed.questions
        proposal: dict[str, Any] | None = None
        if ready and not parsed.safeguarding:
            # Facts the student gave in answers count as stated for the proposal.
            stated = " ".join(v for r in rounds for v in r.answers.values())
            facts = replace(item, description=f"{item.description} {stated}")
            fixed = await fix_rewrite(
                self._ai,
                self._prompts,
                ItemInput(facts, metrics, words),
                parsed.proposal,
                locale,
            )
            proposal = fixed.model_dump() if fixed else None
        doc: dict[str, Any] = {
            "questions": (
                []
                if ready or parsed.safeguarding
                else [
                    {
                        "gap": q.gap,
                        "question": plain(q.question),
                        "why_it_matters": plain(q.why_it_matters),
                        "options": [plain(o) for o in q.options][:MAX_OPTIONS],
                    }
                    for q in parsed.questions[:MAX_QUESTIONS]
                ]
            ),
            "ready": ready,
            "proposal": proposal,
            "safeguarding": parsed.safeguarding,
            "injection_suspected": parsed.injection_suspected,
        }
        async with self._uow() as uow:
            if final:
                last = rounds[-1]
                extra = {k: v for k, v in doc.items() if k != "questions"}
                merged = {**last.questions, **extra}
                await uow.items.update_round(last.id, questions=merged)
                rounds[-1] = replace(last, questions=merged)
            else:
                rounds.append(
                    await uow.items.add_interview(
                        InterviewRound(new_id(), item.id, number, doc)
                    )
                )
            await uow.commit()
        return _state(item.id, rounds)
