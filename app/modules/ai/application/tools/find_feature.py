"""Tool: find the page or bot command of an app where a feature lives."""

from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.domain.tool_args import ToolArgs
from app.settings import UrlsSettings
from app.shared.app_map import search

from pydantic import Field

HIT_LIMIT = 5


class FindFeatureArgs(ToolArgs):
    """What the user wants to do or where to look."""

    query: str = Field(min_length=1, max_length=200)


class FindFeature(ReadTool[FindFeatureArgs]):
    """Pages of the apps, chosen by the user's roles, with their links."""

    name = "find_feature"
    description = "Use when asked where a feature or page is; returns links."
    args_model = FindFeatureArgs

    def __init__(self, urls: UrlsSettings) -> None:
        """Store the origins of the apps."""
        self.urls = urls

    async def run(self, args: FindFeatureArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the best matching pages the user may open."""
        found = search(
            args.query, ctx.locale, ctx.actor.roles, self.urls, limit=HIT_LIMIT
        )
        return {
            "found": bool(found),
            "items": [
                {
                    "title": f.destination.title.get(
                        ctx.locale, f.destination.title["en"]
                    ),
                    "app": f.destination.app,
                    "url": f.url,
                    "command": f.destination.path if f.url is None else None,
                }
                for f in found
            ],
        }
