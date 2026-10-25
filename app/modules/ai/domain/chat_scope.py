"""What a chat is about when it belongs to a place, not only to a user.

The course author assistant works inside one course workspace: its chats carry the
course and the workspace notebook, so every tool call acts on exactly that course.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChatScope(BaseModel):
    """The course workspace of an author chat (``ai.chats.scope``)."""

    model_config = ConfigDict(frozen=True)

    course_id: UUID
    notebook_id: UUID
