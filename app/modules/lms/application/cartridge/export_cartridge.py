"""Use case: download a course draft as a Common Cartridge 1.3."""

import asyncio
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.content_edit import extract_file_ids
from app.modules.lms.domain.authoring.outline import sections_of
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.domain.cartridge.exporter import (
    ExportCourse,
    ExportFile,
    ExportSection,
    export_cartridge,
)
from app.shared.actor import Actor
from app.shared.contracts.files import FilesApi

MAX_EXPORT_FILE_BYTES: Final = 100 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ExportedCartridge:
    """The archive and a file name for it."""

    filename: str
    data: bytes
    notes: list[str]
    title: str = ""


class ExportCartridge:
    """Write the draft (sections, steps, their files) as an .imscc archive."""

    def __init__(self, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.files = files

    async def execute(self, actor: Actor, course_id: UUID) -> ExportedCartridge:
        """Export the course draft.

        Raises:
            CourseNotFoundError: No such course.
            CoursePermissionError: The actor may not edit the course.
        """
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            (await access_to(uow, actor, course_id)).require(EDIT)
            sections_raw = sections_of(course.draft_outline)
            ids = [UUID(s) for section in sections_raw for s in section["steps"]]
            steps = await uow.steps.get_many(ids)
        sections = [
            ExportSection(
                title=str(section["title"]),
                steps=[
                    steps[UUID(s)].draft for s in section["steps"] if UUID(s) in steps
                ],
            )
            for section in sections_raw
        ]
        wanted = sorted(
            {fid for step in steps.values() for fid in extract_file_ids(step.draft)}
        )
        known = await self.files.get_many(wanted) if wanted else {}
        files = {}
        for file_id, ref in known.items():
            if ref.status in {"deleted", "rejected"}:
                continue
            if ref.byte_size > MAX_EXPORT_FILE_BYTES:
                continue
            files[file_id] = ExportFile(ref.name, await self.files.read_bytes(file_id))
        meta = course.draft_meta or {}
        export = ExportCourse(
            title=str(meta.get("title") or course.title),
            description=str(meta.get("description") or ""),
            sections=sections,
            files=files,
        )
        result = await asyncio.to_thread(export_cartridge, export)
        return ExportedCartridge(
            f"{course.slug}.imscc", result.data, result.notes, export.title
        )
