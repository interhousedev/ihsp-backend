"""Adapters that give the media module files and the owner's current rights."""

from uuid import UUID

from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.teaching_scope import TeachingScope


class MediaFilesAdapter:
    """Stores finished media as the owner's private staff files."""

    def __init__(self, files: FilesApi) -> None:
        """Bind the files module."""
        self.files = files

    async def put(
        self, *, owner_id: UUID, name: str, content: bytes, mime: str
    ) -> UUID:
        """Store the bytes; the owner is the only reader until a grant is issued."""
        ref = await self.files.store_bytes(
            owner_id=owner_id,
            scope=FileScope.STAFF,
            purpose=FilePurpose.AI_UPLOAD,
            name=name,
            data=content,
            confidential=True,
        )
        return ref.id


class MediaOwnerAccess:
    """Revalidates the owner's roles and assignment before a paid step."""

    def __init__(self, identity: IdentityDirectory, scope: TeachingScope) -> None:
        """Bind the identity directory and the timetable scope."""
        self.identity = identity
        self.scope = scope

    async def actor_for(
        self, owner_id: UUID, subject_id: UUID, group_id: UUID | None
    ) -> Actor | None:
        """The owner as an actor, or None when the role or assignment is gone."""
        user = await self.identity.get_user(owner_id)
        if user is None or user.status != "active":
            return None
        actor = Actor(user_id=user.id, roles=user.roles)
        if not await self.scope.can_teach(actor, subject_id, group_id):
            return None
        return actor
