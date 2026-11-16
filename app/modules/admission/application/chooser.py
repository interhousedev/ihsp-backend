"""University chooser: catalog search, the student's list, affordability (§11-12)."""

import dataclasses
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.checklist import ensure_entry, ensure_shared
from app.modules.admission.application.estimates import EstimateView, view_estimate
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.domain.chooser import (
    AffordabilityCheck,
    CatalogFilters,
    CatalogInstitution,
    CatalogScholarship,
    ListEntry,
    check_affordability,
    matches,
    needs_affordability_gate,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    AffordabilityGateError,
    AffordabilityRequiredError,
)
from app.modules.admission.domain.estimates import estimate
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.runtime_settings import ESTIMATES_STUDENT_VISIBLE
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import (
    AdmissionUnitOfWork,
    UowFactory,
)
from app.settings_admission import AdmissionSettings
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

MAX_PAGE = 50


@dataclass(frozen=True, slots=True)
class CatalogPage:
    """One page of institutions; `next_cursor` is None on the last page."""

    items: list[CatalogInstitution]
    next_cursor: int | None


class CatalogService:
    """Reads of the catalog; open to every admission user."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Keep the unit-of-work factory."""
        self._uow = uow_factory

    async def search(
        self, filters: CatalogFilters, *, cursor: int = 0, limit: int = 20
    ) -> CatalogPage:
        """Filter institutions by name and facts; offset cursor, name order."""
        limit = max(1, min(limit, MAX_PAGE))
        async with self._uow() as uow:
            found = await uow.catalog.institutions(
                country=filters.country.upper() if filters.country else None
            )
        hits = [i for i in found if matches(i, filters)]
        page = hits[cursor : cursor + limit]
        more = cursor + limit < len(hits)
        return CatalogPage(page, cursor + limit if more else None)

    async def institution(self, institution_id: UUID) -> CatalogInstitution:
        """Return one institution or raise not found."""
        async with self._uow() as uow:
            inst = await uow.catalog.institution(institution_id)
        if inst is None:
            raise AdmissionNotFoundError()
        return inst

    async def scholarships(
        self,
        *,
        institution_id: UUID | None = None,
        country: str | None = None,
        basis: str | None = None,
        coverage_min: int | None = None,
    ) -> list[CatalogScholarship]:
        """List scholarships; the filters are optional."""
        async with self._uow() as uow:
            return await uow.catalog.scholarships(
                institution_id=institution_id,
                country=country.upper() if country else None,
                basis=basis,
                coverage_min=coverage_min,
            )


@dataclass(frozen=True, slots=True)
class ListItem:
    """A list entry with its institution, estimate and affordability."""

    entry: ListEntry
    institution: CatalogInstitution
    estimate: EstimateView
    affordability: AffordabilityCheck | None
    amounts_visible: bool


class ListService:
    """A student's university list; only the owner edits it."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        runtime: RuntimeSettingsService,
        settings: AdmissionSettings,
        clock: Clock,
        identity: IdentityDirectory | None = None,
    ) -> None:
        """Keep the collaborators."""
        self._identity = identity
        self._uow = uow_factory
        self._access = access
        self._runtime = runtime
        self._settings = settings
        self._clock = clock

    async def _visible(self) -> bool:
        rs = await self._runtime.get()
        return bool(
            rs.get(ESTIMATES_STUDENT_VISIBLE, self._settings.estimates_student_visible)
        )

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.require(ctx, ctx.user_id, Permission.LIST_READ)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "list:write"})

    async def _item(
        self,
        ctx: AdmissionContext,
        entry: ListEntry,
        inst: CatalogInstitution,
        check: AffordabilityCheck | None,
        *,
        owner: bool,
        permissions: frozenset[Permission],
        visible: bool,
    ) -> ListItem:
        est = estimate(inst, entry.affordability_status, self._clock.now().year)
        view = view_estimate(
            est,
            inst,
            entry,
            owner=owner,
            staff_uncalibrated=Permission.ESTIMATES_VIEW_UNCALIBRATED in permissions,
            student_visible=visible,
        )
        amounts = owner or Permission.FINANCE_READ in permissions
        return ListItem(entry, inst, view, check, amounts)

    async def view(self, ctx: AdmissionContext, student_id: UUID) -> list[ListItem]:
        """The list of a student the caller may read (the owner or staff)."""
        res = await self._access.require(
            ctx, student_id, Permission.LIST_READ, object_type="list"
        )
        visible = await self._visible()
        async with self._uow() as uow:
            entries = await uow.shortlist.entries(student_id)
            out: list[ListItem] = []
            for e in entries:
                inst = await uow.catalog.institution(e.institution_id)
                if inst is None:
                    continue
                check = await uow.shortlist.affordability(e.id)
                out.append(
                    await self._item(
                        ctx,
                        e,
                        inst,
                        check,
                        owner=res.owner,
                        permissions=res.permissions,
                        visible=visible,
                    )
                )
        return out

    async def add(
        self,
        ctx: AdmissionContext,
        institution_id: UUID,
        *,
        round_: str = "RD",
        bucket: str | None = None,
        notes: str | None = None,
    ) -> ListItem:
        """Put an institution on the caller's list; once per institution."""
        await self._owner(ctx)
        visible = await self._visible()
        async with self._uow() as uow:
            inst = await uow.catalog.institution(institution_id)
            if inst is None:
                raise AdmissionNotFoundError()
            existing = await uow.shortlist.find(ctx.user_id, institution_id)
            if existing is not None:
                await ensure_entry(uow, existing)
                await uow.commit()
                return await self._item(
                    ctx,
                    existing,
                    inst,
                    await uow.shortlist.affordability(existing.id),
                    owner=True,
                    permissions=frozenset(),
                    visible=visible,
                )
            entry = ListEntry(
                id=new_id(),
                student_id=ctx.user_id,
                institution_id=institution_id,
                round=round_,
                bucket=bucket,
                notes=notes,
                lock_version=0,
            )
            entry = await uow.shortlist.add(entry)
            entry, check = await self._recompute(uow, entry, inst)
            await ensure_shared(uow, ctx.user_id)
            await ensure_entry(uow, entry)
            await uow.commit()
        return await self._item(
            ctx,
            entry,
            inst,
            check,
            owner=True,
            permissions=frozenset(),
            visible=visible,
        )

    async def _recompute(
        self, uow: AdmissionUnitOfWork, entry: ListEntry, inst: CatalogInstitution
    ) -> tuple[ListEntry, AffordabilityCheck]:
        """Recompute the check from the stated budget and the published cost.

        A sign-off survives only while the check is still a gap/unknown one.
        """
        band = await uow.shortlist.budget_band(entry.student_id)
        old = await uow.shortlist.affordability(entry.id)
        status, gap = check_affordability(band, inst.coa_total, None)
        kept = old if old is not None and old.signed_off_by is not None else None
        signed = kept is not None
        check = AffordabilityCheck(
            list_entry_id=entry.id,
            coa_total=inst.coa_total,
            confirmed_aid=None,
            estimated_aid=None,
            gap=gap,
            status=status,
            requested_sign_off_at=old.requested_sign_off_at if old else None,
            signed_off_by=kept.signed_off_by if kept else None,
            signed_off_at=kept.signed_off_at if kept else None,
            sign_off_note=kept.sign_off_note if kept else None,
        )
        await uow.shortlist.save_affordability(check)
        new_status = "signed_off" if signed and status != "feasible" else status
        if new_status != entry.affordability_status:
            entry = await uow.shortlist.save(
                dataclasses.replace(entry, affordability_status=new_status),
                expected_lock=entry.lock_version,
            )
        return entry, check

    async def _own_entry(
        self, ctx: AdmissionContext, uow: AdmissionUnitOfWork, entry_id: UUID
    ) -> ListEntry:
        entry = await uow.shortlist.entry(entry_id)
        if entry is None or entry.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return entry

    async def update(
        self,
        ctx: AdmissionContext,
        entry_id: UUID,
        *,
        lock_version: int,
        round_: str | None = None,
        status: str | None = None,
        bucket: str | None = None,
        notes: str | None = None,
        clear_bucket: bool = False,
    ) -> ListItem:
        """Change round, status, bucket or notes; ED/ED2 needs affordability."""
        await self._owner(ctx)
        visible = await self._visible()
        async with self._uow() as uow:
            entry = await self._own_entry(ctx, uow, entry_id)
            inst = await uow.catalog.institution(entry.institution_id)
            if inst is None:
                raise AdmissionNotFoundError()
            changes: dict[str, Any] = {
                k: v
                for k, v in (("round", round_), ("status", status), ("notes", notes))
                if v is not None
            }
            if bucket is not None or clear_bucket:
                changes["bucket"] = bucket
            new = dataclasses.replace(entry, **changes)
            if needs_affordability_gate(new.round, new.affordability_status):
                raise AffordabilityGateError(
                    params={
                        "institution": inst.name,
                        "status": new.affordability_status,
                    }
                )
            new = await uow.shortlist.save(new, expected_lock=lock_version)
            check = await uow.shortlist.affordability(new.id)
            await uow.commit()
        return await self._item(
            ctx,
            new,
            inst,
            check,
            owner=True,
            permissions=frozenset(),
            visible=visible,
        )

    async def remove(self, ctx: AdmissionContext, entry_id: UUID) -> None:
        """Take an institution off the caller's list."""
        await self._owner(ctx)
        async with self._uow() as uow:
            await self._own_entry(ctx, uow, entry_id)
            await uow.shortlist.delete(entry_id)
            await uow.commit()

    async def _staff_entry(
        self,
        ctx: AdmissionContext,
        uow: AdmissionUnitOfWork,
        entry_id: UUID,
        permission: Permission,
    ) -> tuple[ListEntry, frozenset[Permission], bool]:
        entry = await uow.shortlist.entry(entry_id)
        if entry is None:
            raise AdmissionNotFoundError()
        res = await self._access.require(
            ctx,
            entry.student_id,
            permission,
            object_type="list_entry",
            object_id=entry.id,
        )
        return entry, res.permissions, res.owner

    async def estimate(self, ctx: AdmissionContext, entry_id: UUID) -> EstimateView:
        """The estimate of one entry as the caller may see it."""
        visible = await self._visible()
        async with self._uow() as uow:
            entry, perms, owner = await self._staff_entry(
                ctx, uow, entry_id, Permission.LIST_READ
            )
            inst = await uow.catalog.institution(entry.institution_id)
        if inst is None:
            raise AdmissionNotFoundError()
        item = await self._item(
            ctx, entry, inst, None, owner=owner, permissions=perms, visible=visible
        )
        return item.estimate

    async def override_label(
        self,
        ctx: AdmissionContext,
        entry_id: UUID,
        *,
        label: str | None,
        note: str | None,
        lock_version: int,
    ) -> ListEntry:
        """Counselor label override (`None` clears it); audited."""
        async with self._uow() as uow:
            entry, _, _ = await self._staff_entry(
                ctx, uow, entry_id, Permission.LABELS_OVERRIDE
            )
            now = self._clock.now()
            new = dataclasses.replace(
                entry,
                label_override=label,
                override_note=note if label else None,
                override_by=ctx.user_id if label else None,
                override_at=now if label else None,
            )
            new = await uow.shortlist.save(new, expected_lock=lock_version)
            uow.access.audit(
                AuditEvent(
                    action="list.label_override",
                    actor_id=ctx.user_id,
                    student_id=entry.student_id,
                    object_type="list_entry",
                    object_id=entry.id,
                    meta={"label": label, "previous": entry.label_override},
                )
            )
            await uow.commit()
        return new

    async def affordability(
        self, ctx: AdmissionContext, entry_id: UUID
    ) -> tuple[AffordabilityCheck, bool]:
        """Recompute the check; the flag tells whether amounts may be shown."""
        async with self._uow() as uow:
            entry, perms, owner = await self._staff_entry(
                ctx, uow, entry_id, Permission.LIST_READ
            )
            if not owner:
                raise AdmissionForbiddenError(params={"permission": "list:write"})
            inst = await uow.catalog.institution(entry.institution_id)
            if inst is None:
                raise AdmissionNotFoundError()
            _, check = await self._recompute(uow, entry, inst)
            await uow.commit()
        return check, True

    async def request_sign_off(
        self, ctx: AdmissionContext, entry_id: UUID
    ) -> AffordabilityCheck:
        """The student asks a counselor to sign off a gap or unknown cost."""
        async with self._uow() as uow:
            entry, _, owner = await self._staff_entry(
                ctx, uow, entry_id, Permission.LIST_READ
            )
            if not owner:
                raise AdmissionForbiddenError(params={"permission": "list:write"})
            check = await uow.shortlist.affordability(entry.id)
            if check is None:
                raise AffordabilityRequiredError()
            check = dataclasses.replace(check, requested_sign_off_at=self._clock.now())
            await uow.shortlist.save_affordability(check)
            await self._notify_requested(uow, entry.student_id, entry.id, check)
            await uow.commit()
        return check

    async def _notify_requested(
        self,
        uow: AdmissionUnitOfWork,
        student_id: UUID,
        entry_id: UUID,
        check: AffordabilityCheck,
    ) -> None:
        if self._identity is None:
            return
        users = await self._identity.get_users([student_id])
        ref = users.get(student_id)
        name = f"{ref.last_name} {ref.first_name}".strip() if ref else ""
        stamp = check.requested_sign_off_at
        for user_id in await self._identity.user_ids_with_roles([Role.COUNSELOR]):
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.ADMISSION_AFFORDABILITY_SIGNOFF,
                    payload={
                        "event": "requested",
                        "student_name": name,
                        "path": f"/students/view/?id={student_id}&tab=list",
                    },
                    dedupe_key=f"signoff:{entry_id}:requested:{stamp}:{user_id}",
                )
            )

    async def sign_off(
        self, ctx: AdmissionContext, entry_id: UUID, *, note: str | None
    ) -> AffordabilityCheck:
        """A counselor accepts an unresolved cost; audited (§12.2)."""
        async with self._uow() as uow:
            entry, _, _ = await self._staff_entry(
                ctx, uow, entry_id, Permission.AFFORDABILITY_SIGN_OFF
            )
            check = await uow.shortlist.affordability(entry.id)
            if check is None:
                raise AffordabilityRequiredError()
            now = self._clock.now()
            check = dataclasses.replace(
                check,
                signed_off_by=ctx.user_id,
                signed_off_at=now,
                sign_off_note=note,
            )
            await uow.shortlist.save_affordability(check)
            if entry.affordability_status in ("gap", "unknown"):
                await uow.shortlist.save(
                    dataclasses.replace(entry, affordability_status="signed_off"),
                    expected_lock=entry.lock_version,
                )
            uow.access.audit(
                AuditEvent(
                    action="list.affordability_sign_off",
                    actor_id=ctx.user_id,
                    student_id=entry.student_id,
                    object_type="list_entry",
                    object_id=entry.id,
                    meta={"status": check.status},
                )
            )
            uow.notify(
                NotificationDraft(
                    user_id=entry.student_id,
                    type=NotificationType.ADMISSION_AFFORDABILITY_SIGNOFF,
                    payload={
                        "event": "granted",
                        "student_name": "",
                        "path": "/list/",
                    },
                    dedupe_key=f"signoff:{entry.id}:granted:{now}",
                )
            )
            await uow.commit()
        return check
