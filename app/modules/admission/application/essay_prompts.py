"""Looking prompts up: Common App prompts and supplements of the catalog."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
)
from app.modules.admission.domain.essay_flow import (
    PromptRef,
    PromptTarget,
    common_app_refs,
)
from app.modules.admission.ports.consent import SHARING, PurposeConsents
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork


async def find_prompt(
    uow: AdmissionUnitOfWork, institution_id: UUID | None, position: int
) -> PromptRef | None:
    """One prompt by owner and position; None when the catalog has none."""
    if institution_id is None:
        refs = common_app_refs()
    else:
        refs = await uow.prompt_catalog.for_institution(institution_id)
    return next((r for r in refs if r.position == position), None)


async def resolve_targets(
    uow: AdmissionUnitOfWork, targets: Sequence[PromptTarget]
) -> tuple[PromptTarget, ...]:
    """Copy the prompt text and limit of every target without text from the catalog.

    A target already carrying its text keeps it (the draft remembers what it was
    written for). A prompt the catalog does not have is a 404; repeats collapse.
    """
    out: dict[str, PromptTarget] = {}
    for t in targets:
        if t.key in out:
            continue
        if t.prompt:
            out[t.key] = t
            continue
        ref = await find_prompt(uow, t.institution_id, t.position)
        if ref is None:
            raise AdmissionNotFoundError()
        out[t.key] = PromptTarget(
            ref.institution_id, ref.position, ref.prompt, ref.word_limit
        )
    return tuple(out.values())


class FlowGate:
    """The checks every essay-flow call starts with: owner, AI consent, sharing."""

    def __init__(self, access: AccessPolicy, consents: PurposeConsents) -> None:
        """Keep the access policy and the consent reader."""
        self._access = access
        self._consents = consents

    async def owner(self, ctx: AdmissionContext) -> None:
        """Only the student edits their own essays."""
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "essays:edit"})

    async def require(self, ctx: AdmissionContext, purpose: str) -> None:
        """The owner, who has granted the purpose."""
        await self.owner(ctx)
        granted = (await self._consents.granted([ctx.user_id])).get(
            ctx.user_id, frozenset()
        )
        if purpose not in granted:
            raise ConsentRequiredError(params={"purpose": purpose})

    async def sharing(self, user_ids: Sequence[UUID]) -> frozenset[UUID]:
        """The users among `user_ids` who consented to share essays."""
        granted = await self._consents.granted(list(user_ids))
        return frozenset(u for u, p in granted.items() if SHARING in p)
