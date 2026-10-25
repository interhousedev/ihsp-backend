"""Registry that maps a notification type to the function that renders it."""

from app.shared.contracts.notify import Renderer
from app.shared.notifications import NotificationType


class RendererRegistry:
    """Renderers by notification type; the bot module adds its own at startup."""

    def __init__(self) -> None:
        """Start with no renderers."""
        self._renderers: dict[NotificationType, Renderer] = {}

    def register(self, notification_type: NotificationType, renderer: Renderer) -> None:
        """Set the renderer of a type, replacing an earlier one."""
        self._renderers[notification_type] = renderer

    def get(self, notification_type: NotificationType) -> Renderer | None:
        """Return the renderer of a type, or None when nothing is registered."""
        return self._renderers.get(notification_type)
