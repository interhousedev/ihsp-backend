"""Port: the user's profile photo (identity), which a new face also becomes."""

from typing import Protocol
from uuid import UUID


class ProfilePhotos(Protocol):
    """Sets the profile photo that avatars across the apps show."""

    async def set_photo(self, user_id: UUID, data: bytes) -> None:
        """Make the image the user's profile photo, replacing the old one."""
        ...
