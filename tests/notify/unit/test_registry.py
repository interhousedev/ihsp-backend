"""The renderer registry that the bot module adds its renderers to."""

from app.modules.notify.application.renderers.registry import RendererRegistry
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.notifications import NotificationType


async def _first(payload: dict[str, object], ctx: RenderContext) -> RenderedMessage:
    return RenderedMessage(text_html="first")


async def _second(payload: dict[str, object], ctx: RenderContext) -> RenderedMessage:
    return RenderedMessage(text_html="second")


def test_get_returns_none_for_an_unregistered_type() -> None:
    """BOT-11: a type without a renderer is skipped, not an error."""
    registry = RendererRegistry()

    assert registry.get(NotificationType.LESSON_PROMPT) is None


def test_registered_renderer_is_returned_and_can_be_replaced() -> None:
    """The bot module registers lesson_prompt, mail, telegram_linked, otp_reset."""
    registry = RendererRegistry()

    registry.register(NotificationType.MAIL, _first)
    assert registry.get(NotificationType.MAIL) is _first

    registry.register(NotificationType.MAIL, _second)
    assert registry.get(NotificationType.MAIL) is _second
