"""PUT /v1/me/library/progress/{item_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_reader import ProgressBody


async def save_progress(
    item_id: UUID, body: ProgressBody, library: Library, actor: SignedIn
) -> None:
    """Save the reading position (last write wins by `client_ts`)."""
    await library.reader.save_progress.execute(
        actor,
        item_id,
        file_id=body.file_id,
        locator=body.locator,
        percent=body.percent,
        client_ts=body.client_ts,
        seconds_read=body.seconds_read,
    )
