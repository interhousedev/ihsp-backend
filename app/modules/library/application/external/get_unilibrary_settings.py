"""Read the on/off switches of UniLibrary (Administration)."""

from app.modules.library.application.external.gate import ExternalGate
from app.modules.library.ports.external_settings import ExternalFlags
from app.shared.actor import Actor, Role


class GetUniLibrarySettings:
    """`GET /admin/library/unilibrary/settings`: the effective switches."""

    def __init__(self, gate: ExternalGate) -> None:
        """Take the gate that merges the environment and the override."""
        self.gate = gate

    async def execute(self, actor: Actor) -> ExternalFlags:
        """The flags as users experience them now."""
        actor.require(Role.ADMIN)
        return await self.gate.flags()
