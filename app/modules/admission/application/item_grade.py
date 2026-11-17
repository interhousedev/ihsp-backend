"""AI grade (A-E) of the title and description of one activity or honor.

The grade is stored on the item. It is current while the graded text hashes to the
stored `content_hash`; then asking again costs no model call and no quota.
"""

from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review import owned_item, require_ai_consent
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.items import (
    GRADE_LETTERS,
    GRADE_TIP_MAX,
    Item,
    ItemGrade,
    grade_content_hash,
)
from app.modules.admission.infrastructure.ai.prompts import item_grade as prompt
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import PurposeConsents
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand
from app.shared.contracts.ai import AiInvalidOutputError
from app.shared.rate_limit import RateLimiter

_DAY: Final = 24 * 3600
_TOKENS: Final = 400
FALLBACK_GRADE: Final = GRADE_LETTERS[-1]


def _letter(value: Any) -> str | None:
    letter = value.strip().upper() if isinstance(value, str) else ""
    return letter if letter in GRADE_LETTERS else None


def _tip(value: Any) -> str:
    text = nfc(plain(value)) if isinstance(value, str) else ""
    return text[:GRADE_TIP_MAX].strip()


def clean_grade(data: Any, *, content_hash: str, locale: str, model: str) -> ItemGrade:
    """Return the model's grades; an unusable letter is an invalid output."""
    doc = data if isinstance(data, dict) else {}
    title = _letter(doc.get("title_grade"))
    description = _letter(doc.get("description_grade"))
    if title is None or description is None:
        raise AiInvalidOutputError()
    return ItemGrade(
        content_hash=content_hash,
        locale=locale,
        title_grade=title,
        title_tip=_tip(doc.get("title_tip")),
        description_grade=description,
        description_tip=_tip(doc.get("description_tip")),
        model=model,
    )


def item_lines(item: Item, locale: str) -> list[str]:
    """Return the model input: language, then the item's text."""
    return [
        f"Language: {locale}",
        f"[kind] {item.kind}",
        f"[category] {item.category or ''}",
        f"[organization] {item.organization}",
        f"[title] {item.title}",
        f"[description] {item.description}",
    ]


class ItemGradeService:
    """Grade one item of the owner; cache by content, store on the item."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        ai: StructuredAi,
        consents: PurposeConsents,
        prompts: PromptSource,
        limiter: RateLimiter,
        per_day: QuotaOf,
    ) -> None:
        """Keep the collaborators and the reader of the soft daily limit."""
        self._uow = uow_factory
        self._access = access
        self._ai = ai
        self._consents = consents
        self._prompts = prompts
        self._limiter = limiter
        self._per_day = per_day

    async def grade(
        self, ctx: AdmissionContext, item_id: UUID, locale: str
    ) -> ItemGrade:
        """Return the current grade of the item, asking the model only on a miss."""
        async with self._uow() as uow:
            item = await owned_item(self._access, uow, ctx, item_id)
            digest = grade_content_hash(item, locale)
            if item.grade is not None and item.grade.content_hash == digest:
                return item.grade
            await require_ai_consent(self._consents, item.student_id)
        limit = await self._per_day(item.student_id)
        if limit is not None:
            await self._limiter.hit(
                f"admission:item-grade:{item.student_id}",
                limit=limit,
                window_seconds=_DAY,
            )
        data, model = await self._ai.json(
            task=AiTask.ADMIT_ACTIVITY_GRADE,
            system=with_brand(
                await self._prompts.text(AiTask.ADMIT_ACTIVITY_GRADE, "system", locale)
            ),
            user=delimit(item_lines(item, locale)),
            schema_name=prompt.SCHEMA_NAME,
            schema=prompt.SCHEMA,
            max_tokens=_TOKENS,
        )
        grade = clean_grade(data, content_hash=digest, locale=locale, model=model)
        async with self._uow() as uow:
            await uow.items.set_grade(item.id, grade)
            await uow.commit()
        return grade
