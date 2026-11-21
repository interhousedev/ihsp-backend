"""The school grade range an administrator sets (who is entitled, what is planned)."""

from collections.abc import Collection

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.domain.runtime_settings import (
    SCHOOL_GRADES,
    valid_school_grades,
)
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError


class SchoolGradesService:
    """Read for everyone, write for administrators; the env gives the default."""

    def __init__(
        self,
        uow_factory: UowFactory,
        runtime: RuntimeSettingsService,
        default: Collection[int],
    ) -> None:
        """Keep the transaction factory, the runtime snapshot and the env default."""
        self._uow = uow_factory
        self._runtime = runtime
        self._default = tuple(sorted(default))

    async def get(self) -> tuple[int, ...]:
        """Return the grades in force."""
        return (await self._runtime.get()).school_grades(self._default)

    async def set(self, ctx: AdmissionContext, grades: list[int]) -> tuple[int, ...]:
        """Store a contiguous range of grades 1–12 (administrators only)."""
        if Role.ADMIN not in ctx.actor.roles:
            raise AdmissionForbiddenError(params={"permission": "settings:edit"})
        valid = valid_school_grades(grades)
        if valid is None:
            raise ValidationFailedError(params={"field": "grades"})
        async with self._uow() as uow:
            await uow.runtime_settings.save(SCHOOL_GRADES, list(valid), ctx.user_id)
            await uow.commit()
        self._runtime.invalidate()
        return await self.get()
