"""Helpers a student may contact (read) and their curation by staff (CRUD)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.project_ideas import (
    HELP_TAGS,
    Helper,
    clean_helper_values,
    match_helpers,
)
from app.modules.admission.ports.project_ideas import HelperRepository
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.ids import new_id

CanCurate = Callable[[AdmissionContext], bool]


class ProjectHelperService:
    """Active helpers by tag for students; the whole list for curators."""

    def __init__(
        self,
        helpers: HelperRepository,
        uow_factory: UowFactory,
        can_curate: CanCurate,
        clock: Clock,
    ) -> None:
        """Keep the storage, the audit transaction and the curator rule."""
        self._helpers = helpers
        self._uow = uow_factory
        self._can_curate = can_curate
        self._clock = clock

    def _require_curator(self, ctx: AdmissionContext) -> None:
        if not self._can_curate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.CATALOG_CURATE.value}
            )

    async def for_tags(self, tags: list[str]) -> list[Helper]:
        """Active helpers that share a tag, best match first."""
        if any(t not in HELP_TAGS for t in tags):
            raise ValidationFailedError(params={"field": "tag"})
        return match_helpers(await self._helpers.list(active_only=True), tags)

    async def list_all(self, ctx: AdmissionContext) -> list[Helper]:
        """Every helper including inactive ones (curators)."""
        self._require_curator(ctx)
        return await self._helpers.list(active_only=False)

    async def create(self, ctx: AdmissionContext, values: dict[str, Any]) -> Helper:
        """Add a helper."""
        self._require_curator(ctx)
        clean = clean_helper_values(values)
        now = self._clock.now()
        saved = await self._helpers.save(
            Helper(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                **clean,
            )
        )
        await self._audit(ctx, "project_helper.created", saved.id)
        return saved

    async def update(
        self, ctx: AdmissionContext, helper_id: UUID, values: dict[str, Any]
    ) -> Helper:
        """Replace the editable fields of a helper."""
        self._require_curator(ctx)
        current = await self._helpers.get(helper_id)
        if current is None:
            raise AdmissionNotFoundError()
        clean = clean_helper_values(values)
        saved = await self._helpers.save(
            Helper(
                id=current.id,
                created_at=current.created_at,
                updated_at=self._clock.now(),
                created_by=current.created_by,
                **clean,
            )
        )
        await self._audit(ctx, "project_helper.edited", saved.id)
        return saved

    async def delete(self, ctx: AdmissionContext, helper_id: UUID) -> None:
        """Remove a helper."""
        self._require_curator(ctx)
        if not await self._helpers.delete(helper_id):
            raise AdmissionNotFoundError()
        await self._audit(ctx, "project_helper.deleted", helper_id)

    async def _audit(self, ctx: AdmissionContext, action: str, oid: UUID) -> None:
        async with self._uow() as uow:
            uow.access.audit(
                AuditEvent(
                    action=action,
                    actor_id=ctx.user_id,
                    student_id=None,
                    object_type="project_helper",
                    object_id=oid,
                )
            )
            await uow.commit()
