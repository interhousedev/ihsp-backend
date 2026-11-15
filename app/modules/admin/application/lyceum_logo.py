"""Upload, clear and read the lyceum logo (stored in object storage)."""

import hashlib
import logging

from app.modules.admin.domain.lyceum_logo import (
    SETTING_KEY,
    LogoNotFoundError,
    LyceumLogo,
    logo_from_stored,
    sniff_logo,
)
from app.modules.admin.ports.platform_settings_store import PlatformSettingsStore
from app.modules.files.ports.storage import ObjectStorage
from app.shared.actor import Actor, Role

logger = logging.getLogger(__name__)


class LyceumLogoService:
    """The one logo shown on the sign-in page and in the apps."""

    def __init__(self, store: PlatformSettingsStore, storage: ObjectStorage) -> None:
        """Keep the settings store and the object storage."""
        self.store = store
        self.storage = storage

    async def current(self) -> LyceumLogo | None:
        """Return the logo, or None when none was uploaded (no actor check)."""
        return logo_from_stored((await self.store.read_all()).get(SETTING_KEY))

    async def read(self) -> tuple[LyceumLogo, bytes]:
        """Return the logo and its bytes; raises `LogoNotFoundError` when none."""
        logo = await self.current()
        if logo is None:
            raise LogoNotFoundError()
        return logo, await self.storage.get(logo.object_key)

    async def upload(self, actor: Actor, data: bytes) -> LyceumLogo:
        """Check the bytes, store them and replace the previous logo."""
        actor.require(Role.ADMIN)
        content_type = sniff_logo(data)
        digest = hashlib.sha256(data).hexdigest()
        logo = LyceumLogo(f"branding/lyceum-logo/{digest}", digest, content_type)
        previous = await self.current()
        await self.storage.put(logo.object_key, data, content_type)
        await self.store.write(
            {SETTING_KEY: logo.as_stored()}, updated_by=actor.user_id
        )
        if previous is not None and previous.object_key != logo.object_key:
            await self._discard(previous)
        return logo

    async def clear(self, actor: Actor) -> None:
        """Forget the logo and delete its object (best effort)."""
        actor.require(Role.ADMIN)
        previous = await self.current()
        await self.store.delete([SETTING_KEY])
        if previous is not None:
            await self._discard(previous)

    async def _discard(self, logo: LyceumLogo) -> None:
        try:
            await self.storage.delete_many([logo.object_key])
        except Exception:
            logger.warning("lyceum logo object not deleted", exc_info=True)
