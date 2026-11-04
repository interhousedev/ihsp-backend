"""Use case: ZIP of the photos of a group's active students (ADM-PHOTO-2)."""

import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from typing import IO
from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.domain.schedule.errors import GroupNotFoundError
from app.modules.academic.domain.schedule.photo_export import (
    EntryNames,
    detect_photo_extension,
    full_name,
    safe_stem,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory, UserRef
from app.shared.notifications import AuditDraft

import structlog

log = structlog.get_logger(__name__)

AUDIT_GROUP_PHOTOS_EXPORTED = "group.photos_exported"
MANIFEST_NAME = "manifest.txt"
# Photos are read one at a time (at most 5 MiB each); the archive spills to disk
# above this size, so memory stays bounded by one photo, not by the group.
ARCHIVE_MEMORY_BYTES = 8 * 1024 * 1024


@dataclass(slots=True)
class GroupPhotosArchive:
    """The rewound archive, its download name and what it holds.

    The caller streams ``fp`` and closes it.
    """

    fp: IO[bytes]
    filename: str
    exported: int
    missing: tuple[str, ...]


class ExportGroupPhotos:
    """Photos of the active students of one group, named by their full names."""

    def __init__(
        self, uow_factory: UowFactory, identity: IdentityDirectory, files: FilesApi
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.files = files

    async def execute(self, actor: Actor, group_id: UUID) -> GroupPhotosArchive:
        """Build the archive; the same rule as the admin user management applies.

        Raises:
            ForbiddenError: the actor is not an administrator.
            GroupNotFoundError: the group does not exist.
        """
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            students = await uow.students.list_filtered(
                group_id=group_id, status="active"
            )
        users = await self.identity.get_users([s.user_id for s in students])
        people = sorted(
            (users[s.user_id] for s in students if s.user_id in users),
            key=lambda user: full_name(
                user.last_name, user.first_name, user.middle_name
            ).casefold(),
        )
        fp: IO[bytes] = tempfile.SpooledTemporaryFile(max_size=ARCHIVE_MEMORY_BYTES)
        try:
            exported, missing = await self._write(fp, people)
            async with self.uow_factory() as uow:
                uow.audit(
                    AuditDraft(
                        type=AUDIT_GROUP_PHOTOS_EXPORTED,
                        actor_id=actor.user_id,
                        metadata={
                            "group_id": str(group_id),
                            "exported": exported,
                            "missing": len(missing),
                        },
                    )
                )
                await uow.commit()
        except BaseException:
            fp.close()
            raise
        fp.seek(0)
        return GroupPhotosArchive(
            fp=fp,
            filename=f"{safe_stem(group.name, 'group')} photos.zip",
            exported=exported,
            missing=tuple(missing),
        )

    async def _write(
        self, fp: IO[bytes], people: Sequence[UserRef]
    ) -> tuple[int, list[str]]:
        names = EntryNames()
        exported = 0
        missing: list[str] = []
        with zipfile.ZipFile(fp, "w", compression=zipfile.ZIP_STORED) as archive:
            for user in people:
                label = full_name(user.last_name, user.first_name, user.middle_name)
                data = await self._photo(user)
                extension = detect_photo_extension(data) if data else None
                if data is None or extension is None:
                    missing.append(label)
                    continue
                entry = names.claim(f"{safe_stem(label, 'student')}.{extension}")
                archive.writestr(entry, data)
                exported += 1
            manifest = [
                f"Exported: {exported}",
                f"Without photo: {len(missing)}",
                "",
                *missing,
            ]
            archive.writestr(MANIFEST_NAME, "\n".join(manifest).encode("utf-8") + b"\n")
        return exported, missing

    async def _photo(self, user: UserRef) -> bytes | None:
        if user.photo_file_id is None:
            return None
        try:
            return await self.files.read_bytes(user.photo_file_id)
        except BaseError:  # a lost file is reported as missing, not as a failure
            log.warning("group_photo_unavailable", file_id=str(user.photo_file_id))
            return None
