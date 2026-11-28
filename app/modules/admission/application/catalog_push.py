"""Bulk catalog push: a curator's write token upserts countries and institutions."""

from collections.abc import Callable
from typing import Any

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.catalog_push import (
    COUNTRY_BATCH_MAX,
    INSTITUTION_BATCH_MAX,
    PUSH_BATCHES_PER_HOUR,
    PushResult,
    PushStatus,
)
from app.modules.admission.domain.country_facts import (
    clean_as_of,
    clean_facts,
    is_country,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    CatalogPushLimitError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.catalog_push import InstitutionPushWriter
from app.modules.admission.ports.country_facts import CountryFactsRepository
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.base_error import RateLimitedError, ValidationFailedError
from app.shared.rate_limit import RateLimiter

_HOUR = 3_600

CanCurate = Callable[[AdmissionContext], bool]


class CatalogPushService:
    """Upserts pushed batches; one result per item, a bad item never stops others."""

    def __init__(
        self,
        uow_factory: UowFactory,
        countries: CountryFactsRepository,
        institutions: InstitutionPushWriter,
        can_curate: CanCurate,
        limiter: RateLimiter | None = None,
    ) -> None:
        """Keep the audit transaction, both writers, the curator rule and limiter."""
        self._uow = uow_factory
        self._countries = countries
        self._institutions = institutions
        self._can_curate = can_curate
        self._limiter = limiter

    async def push_countries(
        self,
        ctx: AdmissionContext,
        items: list[dict[str, Any]],
        *,
        overwrite_verified: bool = False,
    ) -> list[PushResult]:
        """Upsert country facts by ISO code as drafts; verified rows are skipped."""
        await self._admit(ctx, len(items), COUNTRY_BATCH_MAX)
        codes = [str(i.get("country", "")).strip().upper() for i in items]
        stored = {
            r.country: r
            for r in await self._countries.get_many(
                list(dict.fromkeys(c for c in codes if is_country(c)))
            )
        }
        results: list[PushResult] = []
        for index, (code, item) in enumerate(zip(codes, items, strict=True)):
            if not is_country(code):
                results.append(PushResult(index, code, "invalid", "country"))
                continue
            try:
                as_of = clean_as_of(item.get("as_of"))
                facts = clean_facts(item.get("facts"))
            except ValidationFailedError as e:
                field = str((e.params or {}).get("field", "facts"))
                results.append(PushResult(index, code, "invalid", field))
                continue
            row = stored.get(code)
            status: PushStatus
            if row is not None and row.status == "verified" and not overwrite_verified:
                status = "skipped"
            elif row is not None and row.as_of == as_of and row.facts == facts:
                status = "unchanged"
            else:
                saved = await self._countries.save(
                    code,
                    as_of=as_of,
                    facts=facts,
                    editor=ctx.actor.user_id,
                    verified=False,
                )
                stored[code] = saved
                status = "created" if row is None else "updated"
            results.append(PushResult(index, code, status))
        await self._audit(ctx, "countries", results)
        return results

    async def push_institutions(
        self, ctx: AdmissionContext, items: list[dict[str, Any]]
    ) -> list[PushResult]:
        """Upsert institutions in the seed shape by slug."""
        await self._admit(ctx, len(items), INSTITUTION_BATCH_MAX)
        results = await self._institutions.upsert(items)
        await self._audit(ctx, "institutions", results)
        return results

    async def _admit(self, ctx: AdmissionContext, count: int, most: int) -> None:
        if not self._can_curate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.CATALOG_CURATE.value}
            )
        if not 1 <= count <= most:
            raise ValidationFailedError(params={"field": "items"})
        if self._limiter is None:
            return
        try:
            await self._limiter.hit(
                f"admission:catalog_push:{ctx.user_id}",
                limit=PUSH_BATCHES_PER_HOUR,
                window_seconds=_HOUR,
            )
        except RateLimitedError as e:
            raise CatalogPushLimitError(
                params={**(e.params or {}), "limit": PUSH_BATCHES_PER_HOUR}
            ) from e

    async def _audit(
        self, ctx: AdmissionContext, kind: str, results: list[PushResult]
    ) -> None:
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        async with self._uow() as uow:
            uow.access.audit(
                AuditEvent(
                    action="catalog.pushed",
                    actor_id=ctx.user_id,
                    student_id=None,
                    object_type=f"catalog_{kind}",
                    object_id=None,
                    meta={
                        "counts": counts,
                        "keys": [r.key for r in results if r.status in _WRITTEN],
                    },
                )
            )
            await uow.commit()


_WRITTEN = frozenset({"created", "updated"})
