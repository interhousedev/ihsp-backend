"""The map link template an administrator sets for "open on a map"."""

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.domain.rankings import valid_maps_template
from app.modules.admission.domain.runtime_settings import MAPS_URL_TEMPLATE
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError


class MapsSettingsService:
    """Read for everyone, write for administrators."""

    def __init__(
        self, uow_factory: UowFactory, runtime: RuntimeSettingsService
    ) -> None:
        """Keep the transaction factory and the runtime snapshot."""
        self._uow = uow_factory
        self._runtime = runtime

    async def get(self) -> str | None:
        """Return the template in force, None meaning the default."""
        return (await self._runtime.get()).maps_url_template()

    async def set(self, ctx: AdmissionContext, template: str | None) -> str | None:
        """Store an https template with one `{query}`; None restores the default."""
        if Role.ADMIN not in ctx.actor.roles:
            raise AdmissionForbiddenError(params={"permission": "settings:edit"})
        if template is not None and not valid_maps_template(template):
            raise ValidationFailedError(params={"field": "template"})
        async with self._uow() as uow:
            await uow.runtime_settings.save(
                MAPS_URL_TEMPLATE, template or "", ctx.user_id
            )
            await uow.commit()
        self._runtime.invalidate()
        return await self.get()
