"""Supplemental essay prompts: students read them, curators replace a cycle."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.supp_prompts import (
    MAX_PROMPT_LEN,
    MAX_PROMPTS,
    MAX_PROPOSED_PROMPTS,
    MAX_URL_LEN,
    MAX_WORD_LIMIT,
    CyclePrompts,
    SuppPrompt,
    history,
    valid_cycle,
)
from app.modules.admission.domain.urls import is_https_url
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.base_error import ValidationFailedError


def _clean(prompts: list[SuppPrompt]) -> list[SuppPrompt]:
    """Trim, check and renumber the prompts; raise on an invalid one."""
    if len(prompts) > MAX_PROMPTS:
        raise ValidationFailedError(params={"field": "prompts"})
    out: list[SuppPrompt] = []
    for i, p in enumerate(prompts):
        text = p.prompt.strip()
        if not text or len(text) > MAX_PROMPT_LEN:
            raise ValidationFailedError(params={"field": "prompt"})
        if p.word_limit is not None and not 1 <= p.word_limit <= MAX_WORD_LIMIT:
            raise ValidationFailedError(params={"field": "word_limit"})
        url = (p.source_url or "").strip() or None
        if url is not None and (len(url) > MAX_URL_LEN or not is_https_url(url)):
            raise ValidationFailedError(params={"field": "source_url"})
        out.append(SuppPrompt(i, text, p.word_limit, p.required, url))
    return out


def clean_proposed(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate the prompts of a catalog proposal like the staff PUT does.

    Each item is `{cycle, prompt, word_limit, required, source_url}`; the source
    is mandatory. Raises `ValidationFailedError` naming the invalid field.
    """
    if len(raw) > MAX_PROPOSED_PROMPTS:
        raise ValidationFailedError(params={"field": "supp_prompts"})
    by_cycle: dict[str, list[SuppPrompt]] = {}
    for x in raw:
        cycle = x.get("cycle")
        if not isinstance(cycle, str) or not valid_cycle(cycle):
            raise ValidationFailedError(params={"field": "cycle"})
        url = x.get("source_url")
        if not isinstance(url, str) or not url.strip():
            raise ValidationFailedError(params={"field": "source_url"})
        by_cycle.setdefault(cycle, []).append(
            SuppPrompt(
                0,
                str(x.get("prompt") or ""),
                x.get("word_limit"),
                bool(x.get("required", True)),
                url,
            )
        )
    return [
        {
            "cycle": cycle,
            "prompt": p.prompt,
            "word_limit": p.word_limit,
            "required": p.required,
            "source_url": p.source_url,
        }
        for cycle, prompts in by_cycle.items()
        for p in _clean(prompts)
    ]


async def apply_proposed(
    uow: Any, institution_id: UUID, raw: Sequence[Mapping[str, Any]]
) -> None:
    """Write the approved prompts of a proposal, one cycle at a time.

    Same cleaning and storage as `SuppPromptService.replace`, inside the caller's
    unit of work.
    """
    by_cycle: dict[str, list[SuppPrompt]] = {}
    for x in raw:
        by_cycle.setdefault(x["cycle"], []).append(
            SuppPrompt(0, x["prompt"], x["word_limit"], x["required"], x["source_url"])
        )
    for cycle, prompts in by_cycle.items():
        await uow.supp_prompts.replace(institution_id, cycle, _clean(prompts))


class SuppPromptService:
    """Per-cycle prompts of a catalog institution."""

    def __init__(
        self,
        uow_factory: UowFactory,
        can_curate: Callable[[AdmissionContext], bool],
    ) -> None:
        """Keep the unit of work factory and the catalog-curator check."""
        self._uow = uow_factory
        self._can_curate = can_curate

    async def cycles(self, institution_id: UUID) -> list[CyclePrompts]:
        """Cycles newest first, each prompt marked against the cycle before."""
        async with self._uow() as uow:
            if not await uow.supp_prompts.institution_exists(institution_id):
                raise AdmissionNotFoundError()
            return history(await uow.supp_prompts.by_cycle(institution_id))

    async def replace(
        self,
        ctx: AdmissionContext,
        institution_id: UUID,
        cycle: str,
        prompts: list[SuppPrompt],
    ) -> list[CyclePrompts]:
        """Replace the prompts of one cycle (admin or live catalog curator)."""
        if not self._can_curate(ctx):
            raise AdmissionForbiddenError(params={"permission": "catalog:curate"})
        if not valid_cycle(cycle):
            raise ValidationFailedError(params={"field": "cycle"})
        clean = _clean(prompts)
        async with self._uow() as uow:
            if not await uow.supp_prompts.institution_exists(institution_id):
                raise AdmissionNotFoundError()
            await uow.supp_prompts.replace(institution_id, cycle, clean)
            uow.access.audit(
                AuditEvent(
                    action="catalog.supp_prompts_replaced",
                    actor_id=ctx.user_id,
                    student_id=None,
                    object_type="catalog_institution",
                    object_id=institution_id,
                    meta={"cycle": cycle, "count": len(clean)},
                )
            )
            await uow.commit()
            return history(await uow.supp_prompts.by_cycle(institution_id))
