"""Response model of the app map route."""

from pydantic import BaseModel


class AppMapItem(BaseModel):
    """One page of an app (or a bot command, which has no URL)."""

    id: str
    app: str
    path: str
    url: str | None
    title: dict[str, str]
    keywords: list[str]


class AppMapResponse(BaseModel):
    """The pages the user may open."""

    items: list[AppMapItem]
