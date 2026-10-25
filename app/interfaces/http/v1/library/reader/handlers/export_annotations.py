"""GET /v1/me/library/annotations/export?item_id."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn

from fastapi.responses import PlainTextResponse


async def export_annotations(
    library: Library, actor: SignedIn, item_id: UUID | None = None
) -> PlainTextResponse:
    """The caller's annotations as Markdown text."""
    text = await library.reader.export_annotations.execute(actor, item_id=item_id)
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")
