"""Port for rendering public HTML pages."""

from collections.abc import Mapping
from typing import Any, Protocol


class PageRenderer(Protocol):
    """Renders a named template in a locale."""

    def render(self, template: str, locale: str, context: Mapping[str, Any]) -> str:
        """Return the HTML of the template filled with the context."""
        ...
