"""Callback data of the /start choice and the post tree (at most 64 bytes)."""

from uuid import UUID

from app.shared.ids import b64_to_uuid, uuid_to_b64

from aiogram.filters.callback_data import CallbackData

ROOT = "r"


class StartModeCb(CallbackData, prefix="sm"):
    """The /start choice: ``guest`` or ``student``."""

    mode: str


class PostCb(CallbackData, prefix="po"):
    """Open a post: its id packed in 22 characters, or ``r`` for the main menu."""

    id: str

    @classmethod
    def of(cls, post_id: UUID | None) -> "PostCb":
        """The callback of a post (None: the main menu)."""
        return cls(id=ROOT if post_id is None else uuid_to_b64(post_id))

    def post_id(self) -> UUID | None:
        """The post id, None for the main menu or a malformed id."""
        if self.id == ROOT:
            return None
        try:
            return b64_to_uuid(self.id)
        except ValueError:
            return None
