"""Staff management of the institution list: create, edit, hide, delete."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.catalog_display import LOGO_FITS, valid_logo_zoom
from app.modules.admission.domain.catalog_proposals import (
    INSTITUTION_FIELDS,
    MEDIA_FIELDS,
    invalid_field,
)
from app.modules.admission.domain.catalog_staff import (
    INSTITUTION_STATUSES,
    InstitutionPage,
    StaffInstitution,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CatalogDuplicateError,
    CatalogInUseError,
    InvalidMediaUrlError,
)
from app.modules.admission.domain.intl_facts import clean_name, fold_name
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.urls import is_https_url
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import (
    AdmissionUnitOfWork,
    UowFactory,
)
from app.shared.base_error import ValidationFailedError

CanCurate = Callable[[AdmissionContext], bool]

EDITABLE: tuple[str, ...] = tuple(
    sorted((INSTITUTION_FIELDS - {"programs", "logo_aspect"}) | {"status"})
)
"""Columns a curator may write; `status` is the visibility."""
_REQUIRED = ("name", "country")
_TEXT = ("name", "name_local", "city", "website_domain", "size_band")


def _normalize(key: str, raw: Any) -> Any:
    """Trim one value: empty text becomes None, lists lose blanks and repeats."""
    value = raw
    if key in _TEXT and isinstance(value, str):
        value = clean_name(value) or None
    elif isinstance(value, str):
        value = value.strip() or None
    if key in ("languages", "aliases") and isinstance(value, list):
        value = list(dict.fromkeys(clean_name(v) for v in value if clean_name(v)))
    if key == "country" and isinstance(value, str):
        value = value.upper()
    return value


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    """Return the known fields trimmed, empty ones as None; raise when invalid."""
    cleaned = {k: _normalize(k, v) for k, v in values.items() if k in EDITABLE}
    for key in _REQUIRED:
        if key in cleaned and cleaned[key] is None:
            raise ValidationFailedError(params={"field": key})
    for key in ("languages", "aliases"):
        if key in cleaned and cleaned[key] is None:
            cleaned[key] = []
    for key in ("kind", "logo_zoom"):
        if cleaned.get(key) is None:
            cleaned.pop(key, None)
    probe = {k: v for k, v in cleaned.items() if v is not None}
    bad = invalid_field("institution", probe)
    if bad is not None:
        raise ValidationFailedError(params={"field": bad})
    _check_display(cleaned)
    return cleaned


def _check_display(values: dict[str, Any]) -> None:
    for key in MEDIA_FIELDS:
        if values.get(key) is not None and not is_https_url(values[key]):
            raise InvalidMediaUrlError(params={"field": key})
    if "logo_zoom" in values and not valid_logo_zoom(values["logo_zoom"]):
        raise ValidationFailedError(params={"field": "logo_zoom"})
    fit = values.get("logo_fit")
    if fit is not None and fit not in LOGO_FITS:
        raise ValidationFailedError(params={"field": "logo_fit"})
    status = values.get("status")
    if status is not None and status not in INSTITUTION_STATUSES:
        raise ValidationFailedError(params={"field": "status"})
    if "status" in values and status is None:
        raise ValidationFailedError(params={"field": "status"})


class CatalogStaffService:
    """Administrators and catalog curators manage institutions directly."""

    def __init__(self, uow_factory: UowFactory, can_curate: CanCurate) -> None:
        """Keep the transaction factory and the curator rule."""
        self._uow = uow_factory
        self._can_curate = can_curate

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
        country: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> InstitutionPage:
        """One page of institutions of any status."""
        self.require_curator(ctx)
        async with self._uow() as uow:
            return await uow.catalog_staff.search_institutions(
                query=query.strip() if query else None,
                country=country,
                status=status,
                offset=(page - 1) * page_size,
                limit=page_size,
            )

    async def get(
        self, ctx: AdmissionContext, institution_id: UUID
    ) -> StaffInstitution:
        """One institution of any status."""
        self.require_curator(ctx)
        async with self._uow() as uow:
            found = await uow.catalog_staff.get_institution(institution_id)
        if found is None:
            raise AdmissionNotFoundError()
        return found

    async def create(
        self, ctx: AdmissionContext, values: dict[str, Any]
    ) -> StaffInstitution:
        """Add an institution (published unless `status` says otherwise)."""
        self.require_curator(ctx)
        cleaned = _clean(values)
        for key in _REQUIRED:
            if cleaned.get(key) is None:
                raise ValidationFailedError(params={"field": key})
        cleaned.setdefault("status", "published")
        async with self._uow() as uow:
            await self._reject_duplicate(uow, cleaned)
            new_id = await uow.catalog_staff.create_institution(cleaned)
            self._audit(uow, ctx, "catalog.institution_created", new_id)
            await uow.commit()
            created = await uow.catalog_staff.get_institution(new_id)
        if created is None:
            raise AdmissionNotFoundError()
        return created

    @staticmethod
    async def _reject_duplicate(
        uow: AdmissionUnitOfWork, values: dict[str, Any]
    ) -> None:
        await uow.catalog_proposals.lock_submissions()
        names = [fold_name(n) for n in [values["name"], *values.get("aliases", [])]]
        domain = values.get("website_domain")
        found = await uow.catalog_proposals.find_duplicate(
            names, fold_name(domain) if isinstance(domain, str) else None
        )
        if found is not None:
            which, found_id = found
            raise CatalogDuplicateError(params={f"{which}_id": str(found_id)})

    async def update(
        self,
        ctx: AdmissionContext,
        institution_id: UUID,
        values: dict[str, Any],
        *,
        lock_version: int,
    ) -> StaffInstitution:
        """Overwrite the given fields; a stale `lock_version` conflicts."""
        self.require_curator(ctx)
        cleaned = _clean(values)
        if not cleaned:
            raise ValidationFailedError(params={"field": "fields"})
        async with self._uow() as uow:
            if not await uow.catalog_staff.update_institution(
                institution_id, cleaned, expected_lock=lock_version
            ):
                raise AdmissionNotFoundError()
            self._audit(uow, ctx, "catalog.institution_edited", institution_id)
            await uow.commit()
            saved = await uow.catalog_staff.get_institution(institution_id)
        if saved is None:
            raise AdmissionNotFoundError()
        return saved

    async def delete(self, ctx: AdmissionContext, institution_id: UUID) -> None:
        """Delete an institution nobody uses; otherwise `CatalogInUseError`."""
        self.require_curator(ctx)
        async with self._uow() as uow:
            if await uow.catalog_staff.get_institution(institution_id) is None:
                raise AdmissionNotFoundError()
            if await uow.catalog_staff.institution_in_use(institution_id):
                raise CatalogInUseError(params={"kind": "institution"})
            await uow.catalog_staff.delete_institution(institution_id)
            self._audit(uow, ctx, "catalog.institution_deleted", institution_id)
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
                object_type="catalog_institution",
                object_id=oid,
                meta={},
            )
        )
