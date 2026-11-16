"""The three profile words: confirm, history and AI suggestions."""

import re
from collections.abc import Collection
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    ConsentRequiredError,
    InvalidAnswerError,
    ProfileIncompleteError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.profile import WORDS_COUNT, AdmissionProfile
from app.modules.admission.domain.profile_words import (
    MAX_CANDIDATES,
    WordsSource,
    WordsState,
)
from app.modules.admission.domain.questions import BY_ID
from app.modules.admission.infrastructure.ai.prompts import profile_words as prompt
from app.modules.admission.ports.ai import PromptSource, StructuredAi
from app.modules.admission.ports.consent import AI, PurposeConsents
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.clock import Clock

_MARKUP = re.compile(r"[*_`#<>\[\]()]|https?://\S+")


def plain(text: str) -> str:
    """Strip markdown, links and angle brackets from model text."""
    return " ".join(_MARKUP.sub("", text).split())


def answer_texts(answers: dict[str, Any]) -> dict[str, str]:
    """Return the answers safe to show a model: normal sensitivity, as text."""
    out: dict[str, str] = {}
    for qid, value in sorted(answers.items()):
        q = BY_ID.get(qid)
        if q is None or q.sensitivity != "normal" or q.kind in {"locked", "repeat"}:
            continue
        text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        if text.strip():
            out[qid] = text.strip()
    return out


def delimit(lines: list[str]) -> str:
    """Wrap untrusted student text so a model reads it as data."""
    body = "\n".join(line.replace("</student_text>", "") for line in lines)
    return f"<student_text>\n{body}\n</student_text>"


class WordsService:
    """Read, confirm and suggest the three words."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        clock: Clock,
        prompts: PromptSource,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._consents = consents
        self._clock = clock
        self._prompts = prompts

    async def get(self, ctx: AdmissionContext, student_id: UUID) -> WordsState:
        """Return the words state (empty when none is confirmed yet)."""
        res = await self._access.require(
            ctx, student_id, Permission.WORDS_READ, object_type="words"
        )
        async with self._uow() as uow:
            state = await uow.profiles.get_words(student_id)
        state = state or WordsState(student_id=student_id)
        if not res.owner:
            state.candidates = []
        return state

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "words:edit"})

    async def set(
        self, ctx: AdmissionContext, words: list[str], lock_version: int
    ) -> WordsState:
        """Confirm three words as a new version; the old set goes to history."""
        await self._owner(ctx)
        probe = AdmissionProfile(student_id=ctx.user_id)
        probe.set_words(words)
        clean = probe.words
        if len({w.casefold() for w in clean}) != WORDS_COUNT:
            raise InvalidAnswerError(params={"question": "words"})
        async with self._uow() as uow:
            stored = await uow.profiles.get_words(ctx.user_id)
            if (stored.lock_version if stored else 0) != lock_version:
                raise AdmissionConflictError()
            offered = {
                str(c.get("word", "")).casefold()
                for c in (stored.candidates if stored else [])
            }
            hits = sum(w.casefold() in offered for w in clean)
            source: WordsSource = (
                "ai" if hits == WORDS_COUNT else "mixed" if hits else "manual"
            )
            state = WordsState(
                student_id=ctx.user_id,
                words=clean,
                candidates=stored.candidates if stored else [],
                source=source,
                version=(stored.version if stored else 0) + 1,
                confirmed_at=self._clock.now(),
            )
            saved = await uow.profiles.save_words(
                state, stored.lock_version if stored else None, history=True
            )
            profile = await uow.profiles.get(ctx.user_id)
            if profile is not None and profile.stage in {"setup", "words"}:
                if profile.setup_completed_at is not None:
                    profile.stage = "items"
                    await uow.profiles.save(profile, profile.lock_version)
            await uow.commit()
        return saved

    async def suggest(self, ctx: AdmissionContext) -> WordsState:
        """Ask the model for 8 candidates from the answers; store and return them."""
        await self._owner(ctx)
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if AI not in granted:
            raise ConsentRequiredError(params={"purpose": AI})
        async with self._uow() as uow:
            profile = await uow.profiles.get(ctx.user_id)
        texts = answer_texts(profile.answers) if profile else {}
        if not texts:
            raise ProfileIncompleteError()
        data, _model = await self._ai.json(
            task=AiTask.ADMIT_PROFILE_WORDS,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_PROFILE_WORDS, "system", "")
            ),
            user=delimit([f"[answer:{k}] {v}" for k, v in texts.items()]),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=1500,
        )
        candidates = self._clean(data, set(texts))
        async with self._uow() as uow:
            stored = await uow.profiles.get_words(ctx.user_id)
            state = stored or WordsState(student_id=ctx.user_id)
            state.candidates = candidates
            saved = await uow.profiles.save_words(
                state, stored.lock_version if stored else None, history=False
            )
            await uow.commit()
        return saved

    @staticmethod
    def _clean(data: dict[str, Any], known: Collection[str]) -> list[dict[str, Any]]:
        """Keep valid, distinct, plain candidates with known evidence."""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in data.get("candidates", []):
            word = plain(str(raw.get("word", "")))
            key = word.casefold()
            if not word or len(word) > 40 or key in seen:
                continue
            seen.add(key)
            refs = [
                r
                for r in (
                    str(x).removeprefix("answer:") for x in raw.get("evidence_refs", [])
                )
                if r in known
            ]
            out.append(
                {
                    "word": word,
                    "reason": plain(str(raw.get("reason", "")))[:240],
                    "evidence_refs": refs,
                }
            )
        return out[:MAX_CANDIDATES]
