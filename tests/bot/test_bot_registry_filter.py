"""The per-bot feature filter: unregistered bots keep every feature."""

from types import SimpleNamespace

from app.interfaces.bot.middlewares.bot_registry import BotAllows
from app.modules.admin.domain.telegram_bot import BotFeature


class Registry:
    def __init__(self, allowed: set[tuple[int, BotFeature]]) -> None:
        self.allowed = allowed

    async def allows(self, telegram_id: int, feature: BotFeature) -> bool:
        return (telegram_id, feature) in self.allowed


async def test_without_registry_every_feature_passes() -> None:
    bot = SimpleNamespace(id=1)
    assert await BotAllows(BotFeature.AI_AGENT)(object(), bot)  # type: ignore[arg-type]


async def test_registry_decides_per_bot() -> None:
    registry = Registry({(1, BotFeature.AI_AGENT)})
    check = BotAllows(BotFeature.AI_AGENT)
    one, two = SimpleNamespace(id=1), SimpleNamespace(id=2)
    assert await check(object(), one, registry)  # type: ignore[arg-type]
    assert not await check(object(), two, registry)  # type: ignore[arg-type]
