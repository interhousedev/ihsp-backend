"""Routes of sharing a file: link, people and "shared with me" (FILE-SHARE)."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.files.schemas import DownloadUrlResponse
from app.interfaces.http.v1.files.schemas_shares import (
    FileShareLinkResponse,
    FileSharePersonResponse,
    FileSharesResponse,
    JoinFileShareBody,
    SharedFileItem,
    SharedFilesResponse,
)
from app.modules.files.domain.errors import FileShareRecipientNotFoundError
from app.modules.files.domain.stored_file import StoredFile
from app.shared.actor import Actor
from app.shared.contracts.identity import UserRef, UserStatus

from fastapi import Depends, Query

ActorDep = Annotated[Actor, Depends(get_actor)]
ContainerDep = Annotated[Container, Depends(get_container)]


def _name(user: UserRef | None) -> str:
    return "" if user is None else f"{user.first_name} {user.last_name}".strip()


def _item(file: StoredFile, owner_name: str) -> SharedFileItem:
    return SharedFileItem(
        id=file.id,
        name=file.name,
        content_type=file.content_type,
        byte_size=file.byte_size,
        created_at=file.created_at,
        owner_name=owner_name,
    )


async def _users(container: Container, ids: list[UUID]) -> dict[UUID, UserRef]:
    if not ids or container.identity is None:
        return {}
    return await container.identity.directory.get_users(ids)


async def get_file_shares(
    file_id: UUID, actor: ActorDep, container: ContainerDep
) -> FileSharesResponse:
    """Who has access (the owner only)."""
    state = await container.files.manage_shares.state(actor, file_id)
    users = await _users(container, [p.user_id for p in state.people])
    return FileSharesResponse(
        link_active=state.link_active,
        people=[
            FileSharePersonResponse(
                user_id=p.user_id,
                name=_name(users.get(p.user_id)),
                via=p.via,
                created_at=p.created_at,
            )
            for p in state.people
        ],
    )


async def create_file_share_link(
    file_id: UUID, actor: ActorDep, container: ContainerDep
) -> FileShareLinkResponse:
    """Create the link or replace its token; the token is shown this once."""
    token = await container.files.manage_shares.create_link(actor, file_id)
    return FileShareLinkResponse(token=token)


async def delete_file_share_link(
    file_id: UUID, actor: ActorDep, container: ContainerDep
) -> None:
    """Turn the link off and remove everyone who joined through it."""
    await container.files.manage_shares.delete_link(actor, file_id)


async def add_file_share_person(
    file_id: UUID, user_id: UUID, actor: ActorDep, container: ContainerDep
) -> None:
    """Give a person access to download the file."""
    if user_id != actor.user_id:
        users = await _users(container, [user_id])
        user = users.get(user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise FileShareRecipientNotFoundError()
    await container.files.manage_shares.add_person(actor, file_id, user_id)


async def remove_file_share_person(
    file_id: UUID, user_id: UUID, actor: ActorDep, container: ContainerDep
) -> None:
    """Revoke a person's access at once."""
    await container.files.manage_shares.remove_person(actor, file_id, user_id)


async def join_file_share(
    body: JoinFileShareBody, actor: ActorDep, container: ContainerDep
) -> SharedFileItem:
    """Open a share link: a signed-in person gets their own grant."""
    file = await container.files.manage_shares.join(actor, body.token)
    users = await _users(container, [file.owner_id])
    return _item(file, _name(users.get(file.owner_id)))


async def leave_shared_file(
    file_id: UUID, actor: ActorDep, container: ContainerDep
) -> None:
    """The recipient removes a shared file from their list."""
    await container.files.manage_shares.leave(actor, file_id)


async def get_shared_file_url(
    file_id: UUID,
    actor: ActorDep,
    container: ContainerDep,
    inline: Annotated[bool | None, Query()] = None,
) -> DownloadUrlResponse:
    """Presign a GET for a recipient; valid for 60 seconds."""
    result = await container.files.manage_shares.download_url(actor, file_id, inline)
    return DownloadUrlResponse(url=result.url, expires_at=result.expires_at)


async def list_shared_files(
    actor: ActorDep, container: ContainerDep
) -> SharedFilesResponse:
    """The files shared with the caller."""
    files = await container.files.manage_shares.list_shared(actor)
    users = await _users(container, [file.owner_id for file in files])
    return SharedFilesResponse(
        items=[_item(file, _name(users.get(file.owner_id))) for file in files]
    )
