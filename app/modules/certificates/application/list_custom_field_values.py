"""Distinct values of one custom field, for the staff filters."""

from dataclasses import dataclass, replace
from typing import Any

from app.modules.certificates.application.list_staff_entries import repo_filter
from app.modules.certificates.application.staff_scope import StaffFilters, StaffScope
from app.modules.certificates.domain.custom_fields import CustomField, FieldKind
from app.modules.certificates.domain.errors import (
    CertificateInvalidError,
    CertificateTypeNotFoundError,
)
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class CustomFieldValues:
    """What a filter for one field offers.

    ``options`` are the defined choices. ``other_values`` are the values in the
    data that are not defined choices (free text), or all distinct texts for a
    text field. ``min`` and ``max`` are set for number fields.
    """

    field: CustomField
    options: list[str]
    other_values: list[str]
    min: float | None
    max: float | None


class ListCustomFieldValues:
    """Values of a custom field over the students and type the caller may see."""

    def __init__(self, *, uow_factory: UowFactory, scope: StaffScope) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._scope = scope

    async def execute(
        self, actor: Actor, flt: StaffFilters, key: str
    ) -> CustomFieldValues:
        """Return the field's choices and the values stored for it."""
        if flt.type_id is None:
            raise CertificateInvalidError(params={"field": "type_id"})
        students = await self._scope.students(actor, flt)
        async with self._uow_factory() as uow:
            kind = await uow.types.get(flt.type_id)
            if kind is None:
                raise CertificateTypeNotFoundError()
            item = next((f for f in kind.custom_fields if f.key == key), None)
            if item is None:
                raise CertificateInvalidError(params={"field": key})
            rows, _ = await uow.entries.query(
                repo_filter(students, replace(flt, custom={}, ranges={})),
                limit=None,
                offset=0,
            )
        return _summarize(item, [row.custom_values.get(key) for row in rows])


def _summarize(item: CustomField, stored: list[Any]) -> CustomFieldValues:
    if item.kind is FieldKind.NUMBER:
        numbers = [v for v in stored if isinstance(v, int | float)]
        return CustomFieldValues(
            item,
            [],
            [],
            min(numbers) if numbers else None,
            max(numbers) if numbers else None,
        )
    seen: set[str] = set()
    for value in stored:
        for text in value if isinstance(value, list) else [value]:
            if isinstance(text, str):
                seen.add(text)
    if item.kind is FieldKind.TEXT:
        others = seen
    else:
        others = seen - set(item.options)
    return CustomFieldValues(
        item, list(item.options), sorted(others, key=str.casefold), None, None
    )
