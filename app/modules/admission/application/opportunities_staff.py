"""Staff management of the opportunities catalog: list, edit, hide, delete."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.opportunities import LmsCourseLookup
from app.modules.admission.domain.catalog_staff import OpportunityState
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CatalogInUseError,
    InvalidProofUrlError,
)
from app.modules.admission.domain.opportunities import Opportunity, OpportunityDraft
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.urls import is_https_url
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import (
    AdmissionUnitOfWork,
    UowFactory,
)
from app.shared.base_error import ValidationFailedError

CanCurate = Callable[[AdmissionContext], bool]

_ARCHIVED: dict[str, bool | None] = {"all": None, "live": False, "archived": True}


class OpportunityStaffService:
    """Administrators and catalog curators manage every entry directly."""

    def __init__(
        self,
        uow_factory: UowFactory,
        can_curate: CanCurate,
        lms: LmsCourseLookup | None = None,
        org_exists: Callable[[UUID], Awaitable[bool]] | None = None,
    ) -> None:
        """Keep the transaction factory and the collaborators."""
        self._uow = uow_factory
        self._can_curate = can_curate
        self._lms = lms
        self._org_exists = org_exists

    def require_curator(self, ctx: AdmissionContext) -> None:
        """Raise `AdmissionForbiddenError` unless the caller may curate."""
        if not self._can_curate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.CATALOG_CURATE.value}
            )

    async def search(
        self,
        ctx: AdmissionContext,
        *,
        query: str | None,
        kind: str | None,
        state: OpportunityState,
        page: int,
        page_size: int,
    ) -> tuple[list[Opportunity], int]:
        """One page of entries, live and archived, and the total."""
        self.require_curator(ctx)
        async with self._uow() as uow:
            return await uow.catalog_staff.search_opportunities(
                query=query.strip() if query else None,
                kind=kind,
                archived=_ARCHIVED[state],
                offset=(page - 1) * page_size,
                limit=page_size,
            )

    async def get(
        self, ctx: AdmissionContext, opportunity_id: UUID
    ) -> tuple[Opportunity, bool]:
        """One entry and whether student data refers to it."""
        self.require_curator(ctx)
        async with self._uow() as uow:
            found = await uow.opportunities.get(opportunity_id)
            if found is None:
                raise AdmissionNotFoundError()
            return found, await uow.catalog_staff.opportunity_in_use(opportunity_id)

    async def _validate(
        self, uow: AdmissionUnitOfWork, draft: OpportunityDraft
    ) -> None:
        bad = draft.problems()
        if bad:
            raise ValidationFailedError(params={"field": bad[0]})
        if not all(is_https_url(u) for u in draft.urls()):
            raise InvalidProofUrlError()
        taxonomy = await uow.opportunities.taxonomy()
        subjects = {n.id for n in taxonomy if n.level == "subject"}
        if not set(draft.subject_ids) <= subjects:
            raise ValidationFailedError(params={"field": "subject_ids"})
        courses = [draft.lms_course_id, *(m.lms_course_id for m in draft.materials)]
        for course_id in {c for c in courses if c is not None}:
            if self._lms is None or await self._lms.course_title(course_id) is None:
                raise ValidationFailedError(params={"field": "lms_course_id"})
        if (
            draft.org_id is not None
            and self._org_exists is not None
            and not await self._org_exists(draft.org_id)
        ):
            raise ValidationFailedError(params={"field": "org_id"})

    async def create(
        self, ctx: AdmissionContext, draft: OpportunityDraft
    ) -> Opportunity:
        """Publish a new entry without moderation."""
        self.require_curator(ctx)
        async with self._uow() as uow:
            await self._validate(uow, draft)
            new_id = await uow.opportunities.apply(
                draft, target_id=None, by=ctx.user_id
            )
            self._audit(uow, ctx, "opportunity.staff_created", new_id)
            await uow.commit()
            created = await uow.opportunities.get(new_id)
        if created is None:
            raise AdmissionNotFoundError()
        return created

    async def update(
        self,
        ctx: AdmissionContext,
        opportunity_id: UUID,
        draft: OpportunityDraft,
        *,
        lock_version: int,
    ) -> Opportunity:
        """Overwrite every field of an entry; a stale `lock_version` conflicts."""
        self.require_curator(ctx)
        async with self._uow() as uow:
            current = await uow.opportunities.get(opportunity_id)
            if current is None:
                raise AdmissionNotFoundError()
            if current.lock_version != lock_version:
                raise AdmissionConflictError()
            await self._validate(uow, draft)
            await uow.opportunities.apply(
                draft, target_id=opportunity_id, by=ctx.user_id
            )
            self._audit(uow, ctx, "opportunity.staff_edited", opportunity_id)
            await uow.commit()
            saved = await uow.opportunities.get(opportunity_id)
        if saved is None:
            raise AdmissionNotFoundError()
        return saved

    async def set_archived(
        self, ctx: AdmissionContext, opportunity_id: UUID, archived: bool
    ) -> Opportunity:
        """Hide an entry from students or bring it back."""
        self.require_curator(ctx)
        async with self._uow() as uow:
            if await uow.opportunities.get(opportunity_id) is None:
                raise AdmissionNotFoundError()
            await uow.opportunities.set_archived(opportunity_id, archived)
            self._audit(
                uow,
                ctx,
                "opportunity.archived" if archived else "opportunity.restored",
                opportunity_id,
            )
            await uow.commit()
            saved = await uow.opportunities.get(opportunity_id)
        if saved is None:
            raise AdmissionNotFoundError()
        return saved

    async def delete(self, ctx: AdmissionContext, opportunity_id: UUID) -> None:
        """Delete an entry nobody uses; otherwise `CatalogInUseError`."""
        self.require_curator(ctx)
        async with self._uow() as uow:
            if await uow.opportunities.get(opportunity_id) is None:
                raise AdmissionNotFoundError()
            if await uow.catalog_staff.opportunity_in_use(opportunity_id):
                raise CatalogInUseError(params={"kind": "opportunity"})
            await uow.catalog_staff.delete_opportunity(opportunity_id)
            self._audit(uow, ctx, "opportunity.staff_deleted", opportunity_id)
            await uow.commit()

    @staticmethod
    def _audit(
        uow: AdmissionUnitOfWork, ctx: AdmissionContext, action: str, oid: UUID
    ) -> None:
        uow.access.audit(
            AuditEvent(
                action=action,
                actor_id=ctx.user_id,
                student_id=None,
                object_type="opportunity",
                object_id=oid,
                meta={},
            )
        )
