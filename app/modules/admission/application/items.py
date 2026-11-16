"""Activities and honors with their metrics (§9): list, edit, order, summary."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review import (
    TARGET_KIND,
    owned_item,
    review_hash,
)
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.review_prompts import LANGUAGES
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    ItemLimitError,
    ProjectedDateRequiredError,
)
from app.modules.admission.domain.items import MAX_ACTIVITIES, MAX_HONORS, Item
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.items import Horizon, Metric, StoredReview
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ids import new_id

LABEL_MAX: Final = 80
UNIT_MAX: Final = 24
MAX_METRICS: Final = 8
EDITABLE: Final = frozenset(
    {
        "title",
        "organization",
        "description",
        "category",
        "grades",
        "hours_per_week",
        "weeks_per_year",
    }
)


@dataclass(frozen=True, slots=True)
class MetricDraft:
    """A metric as the student enters it."""

    label: str
    value: Decimal
    unit: str | None = None
    horizon: Horizon = "current"
    as_of: date | None = None
    target_date: date | None = None


@dataclass(frozen=True, slots=True)
class ItemView:
    """An item with its metrics and its newest review; `stale` = input changed."""

    item: Item
    metrics: list[Metric]
    review: StoredReview | None
    stale: bool


def items_summary(
    items: Sequence[Item], metrics: Mapping[UUID, Sequence[Metric]]
) -> list[dict[str, Any]]:
    """Return a compact view of the items for alignment; plans are marked.

    Pure: no I/O. Planned numbers carry their target date so a consumer never
    reads them as achieved.
    """
    out: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda i: (i.kind, i.position)):
        facts = []
        for m in metrics.get(item.id, ()):
            unit = f" {m.unit}" if m.unit else ""
            when = f" (planned by {m.target_date})" if m.horizon == "projected" else ""
            value = format(m.value.normalize(), "f")
            facts.append(f"{m.label}: {value}{unit}{when}")
        out.append(
            {
                "id": str(item.id),
                "kind": item.kind,
                "position": item.title,
                "organization": item.organization,
                "description": item.description,
                "hours_per_week": item.hours_per_week,
                "weeks_per_year": item.weeks_per_year,
                "metrics": facts,
            }
        )
    return out


def _metric(item_id: UUID, draft: MetricDraft) -> Metric:
    label = nfc(draft.label).strip()
    if not label or len(label) > LABEL_MAX:
        raise CharLimitError(
            params={"field": "label", "limit": LABEL_MAX, "count": len(label)}
        )
    unit = nfc(draft.unit).strip() if draft.unit else None
    if unit and len(unit) > UNIT_MAX:
        raise CharLimitError(
            params={"field": "unit", "limit": UNIT_MAX, "count": len(unit)}
        )
    if draft.horizon == "projected" and draft.target_date is None:
        raise ProjectedDateRequiredError(params={"field": "target_date"})
    return Metric(
        id=new_id(),
        item_id=item_id,
        label=label,
        value=draft.value,
        unit=unit or None,
        horizon=draft.horizon,
        as_of=draft.as_of if draft.horizon == "current" else None,
        target_date=draft.target_date if draft.horizon == "projected" else None,
    )


class ItemService:
    """CRUD of a student's items; only the owner edits, staff read in scope."""

    def __init__(self, uow_factory: UowFactory, access: AccessPolicy) -> None:
        """Keep the transaction factory and the access policy."""
        self._uow = uow_factory
        self._access = access

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "activities:edit"})

    async def list_items(
        self, ctx: AdmissionContext, student_id: UUID
    ) -> list[ItemView]:
        """Return the student's items with metrics and the newest reviews."""
        await self._access.require(
            ctx, student_id, Permission.ACTIVITIES_READ, object_type="items"
        )
        async with self._uow() as uow:
            items = await uow.items.list_for(student_id)
            metrics = await uow.items.metrics_for([i.id for i in items])
            words = await uow.items.words(student_id)
            reviews = {
                i.id: await uow.items.latest_review(TARGET_KIND, i.id) for i in items
            }
            await uow.commit()
        views: list[ItemView] = []
        for item in items:
            ms = metrics.get(item.id, [])
            review = reviews[item.id]
            stale = False
            if review is not None:
                current = (
                    {review_hash(item, ms, words, loc) for loc in LANGUAGES}
                    if words
                    else set()
                )
                stale = review.input_hash not in current
            views.append(ItemView(item, ms, review, stale))
        return views

    async def summary(
        self, ctx: AdmissionContext, student_id: UUID
    ) -> list[dict[str, Any]]:
        """Return `items_summary` of a student the caller may read."""
        views = await self.list_items(ctx, student_id)
        return items_summary(
            [v.item for v in views], {v.item.id: v.metrics for v in views}
        )

    async def create(
        self, ctx: AdmissionContext, item: Item, metrics: Sequence[MetricDraft] = ()
    ) -> ItemView:
        """Add an item at the end of its kind; caps: 10 activities, 5 honors."""
        await self._owner(ctx)
        limit = MAX_HONORS if item.kind == "honor" else MAX_ACTIVITIES
        draft = replace(item, id=new_id(), student_id=ctx.user_id, lock_version=0)
        draft.validate()
        if len(metrics) > MAX_METRICS:
            raise ItemLimitError(params={"kind": "metric", "limit": MAX_METRICS})
        async with self._uow() as uow:
            all_items = await uow.items.list_for(ctx.user_id)
            same = [i for i in all_items if i.kind == item.kind]
            if len(same) >= limit:
                raise ItemLimitError(params={"kind": item.kind, "limit": limit})
            draft.position = max((i.position for i in same), default=-1) + 1
            stored = await uow.items.add(draft)
            rows = [_metric(stored.id, m) for m in metrics]
            if rows:
                await uow.items.replace_metrics(stored.id, rows)
            await uow.commit()
        return ItemView(stored, rows, None, False)

    async def update(
        self,
        ctx: AdmissionContext,
        item_id: UUID,
        changes: Mapping[str, Any],
        lock_version: int,
    ) -> Item:
        """Change fields of an item; a stale `lock_version` is a conflict."""
        unknown = set(changes) - EDITABLE
        if unknown:
            raise AdmissionForbiddenError(params={"permission": "activities:edit"})
        async with self._uow() as uow:
            item = await owned_item(self._access, uow, ctx, item_id)
            if item.lock_version != lock_version:
                raise AdmissionConflictError()
            updated = replace(item, **dict(changes))
            updated.validate()
            stored = await uow.items.update(updated)
            await uow.commit()
        return stored

    async def delete(self, ctx: AdmissionContext, item_id: UUID) -> None:
        """Delete an item with its metrics, interviews and proofs."""
        async with self._uow() as uow:
            await owned_item(self._access, uow, ctx, item_id)
            await uow.items.delete(item_id)
            await uow.commit()

    async def order(self, ctx: AdmissionContext, ordered: Sequence[UUID]) -> None:
        """Set the display order; every id must be one of the caller's items."""
        await self._owner(ctx)
        async with self._uow() as uow:
            own = {i.id for i in await uow.items.list_for(ctx.user_id)}
            if len(set(ordered)) != len(ordered) or not set(ordered) <= own:
                raise AdmissionNotFoundError()
            await uow.items.set_order(list(ordered))
            await uow.commit()

    async def set_metrics(
        self, ctx: AdmissionContext, item_id: UUID, metrics: Sequence[MetricDraft]
    ) -> list[Metric]:
        """Replace the metrics of an item; plans need a target date."""
        if len(metrics) > MAX_METRICS:
            raise ItemLimitError(params={"kind": "metric", "limit": MAX_METRICS})
        async with self._uow() as uow:
            item = await owned_item(self._access, uow, ctx, item_id)
            rows = [_metric(item.id, m) for m in metrics]
            await uow.items.replace_metrics(item.id, rows)
            await uow.commit()
        return rows
