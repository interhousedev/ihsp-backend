"""Create a certificate type (administrator)."""

from collections.abc import Mapping
from typing import Any

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.errors import CertificateTypeCodeTakenError
from app.modules.certificates.domain.type_rules import apply_changes
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.ids import new_id


class CreateType:
    """Add a custom (not built-in) type."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, fields: Mapping[str, Any]) -> CertificateType:
        """Create the type from the input fields; the code must be free."""
        kind = CertificateType(id=new_id(), code=str(fields.get("code", "")), name={})
        apply_changes(kind, fields)
        async with self._uow_factory() as uow:
            if await uow.types.get_by_code(kind.code) is not None:
                raise CertificateTypeCodeTakenError()
            if "position" not in fields:
                kind.position = await uow.types.next_position()
            await uow.types.add(kind)
            await uow.commit()
        return kind
