"""`find_feature`: shared body of the tool on the Students, LMS and Admin servers."""

from typing import Annotated, Any

from app.interfaces.mcp.deps import McpDeps
from app.shared.actor import Actor
from app.shared.app_map import hidden_pages, search

from pydantic import Field

QueryParam = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        description="What the user wants to do or find, in any language.",
    ),
]
HIT_LIMIT = 5


def find_feature_result(deps: McpDeps, actor: Actor, query: str) -> dict[str, Any]:
    """Pages of the apps that fit the query and that the actor's roles may open."""
    found = search(
        query,
        "en",
        actor.roles,
        deps.settings.urls,
        limit=HIT_LIMIT,
        hidden=hidden_pages(deps.settings.features),
    )
    return {
        "found": bool(found),
        "items": [
            {
                "app": f.destination.app,
                "titles": f.destination.title,
                "url": f.url,
                "command": f.destination.path if f.url is None else None,
            }
            for f in found
        ],
    }
