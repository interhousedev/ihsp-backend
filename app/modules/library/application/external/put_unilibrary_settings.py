"""Switch UniLibrary on or off at runtime (Administration)."""

from app.modules.library.ports.external_settings import (
    ExternalFlags,
    ExternalSettingsStore,
)
from app.shared.actor import Actor, Role

import structlog

log = structlog.get_logger(__name__)


class PutUniLibrarySettings:
    """`PUT /admin/library/unilibrary/settings {enabled, anonymous_cards}`.

    The values live in Redis (`library:ext:settings`) and beat the environment, so
    no restart is needed. The first switch-on is Administration's decision (doc Q1).
    """

    def __init__(self, store: ExternalSettingsStore) -> None:
        """Take the store of the override."""
        self.store = store

    async def execute(
        self, actor: Actor, *, enabled: bool, anonymous_cards: bool
    ) -> ExternalFlags:
        """Store both switches and return them."""
        actor.require(Role.ADMIN)
        flags = ExternalFlags(enabled=enabled, anonymous_cards=anonymous_cards)
        await self.store.save(flags)
        log.info(
            "library_unilibrary_settings_changed",
            actor_id=str(actor.user_id),
            enabled=enabled,
            anonymous_cards=anonymous_cards,
        )
        return flags
