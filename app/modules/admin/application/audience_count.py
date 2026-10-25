"""Show how many people a broadcast audience reaches (UF-ADM-08 step 2)."""

from app.modules.admin.application.resolve_audience import ResolveAudience
from app.modules.admin.domain.audience import Audience
from app.shared.actor import Actor, Role


class AudienceCount:
    """Counts the recipients of an audience."""

    def __init__(self, resolver: ResolveAudience) -> None:
        """Store the audience resolver."""
        self.resolver = resolver

    async def execute(self, actor: Actor, audience: Audience) -> int:
        """Return the number of active recipients."""
        actor.require(Role.ADMIN)
        return len(await self.resolver.execute(audience))
