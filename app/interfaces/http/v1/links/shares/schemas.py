"""Request body of /v1/shares."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel


class CreateShareBody(BaseModel):
    """Share a chat or a flash card set."""

    kind: Literal["chat", "flashcard_set"]
    target_id: UUID
    share_mode: Literal["snapshot", "live"] | None = None
    expires_at: AwareDatetime | None = None
