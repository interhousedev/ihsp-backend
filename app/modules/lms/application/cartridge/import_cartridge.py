"""Use case: create a course from a Common Cartridge (runs in the worker)."""

import asyncio
import posixpath
import re
import secrets
import unicodedata
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.lms.application.authoring.access import load_course_locked
from app.modules.lms.application.authoring.create_course import CreateCourse
from app.modules.lms.application.authoring.draft_writer import StepDraftWriter
from app.modules.lms.application.authoring.outline_editor import record_draft_change
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.entities import CourseStep
from app.modules.lms.domain.authoring.enums import StepVia, Visibility
from app.modules.lms.domain.authoring.errors import ContentInvalidError
from app.modules.lms.domain.authoring.hashing import outline_hash
from app.modules.lms.domain.authoring.outline import AddSection, add_step, apply_ops
from app.modules.lms.domain.cartridge.archive import CartridgeArchive
from app.modules.lms.domain.cartridge.importer import (
    ASSET_PREFIX,
    ImportPlan,
    ImportReport,
    plan_import,
)
from app.modules.lms.domain.step_content import Block, StepContent
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.ids import new_id
from app.shared.jobs import JobCancelled, job_progress, job_should_stop

from pydantic import TypeAdapter, ValidationError

_ASSET: Final = re.compile(re.escape(ASSET_PREFIX) + r"(\d+)")
_BLOCK: Final[TypeAdapter[Any]] = TypeAdapter(Block)


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """The new course and the report."""

    course_id: UUID
    report: ImportReport


class ImportCartridge:
    """Upload the files, create the course, then its sections and steps at once."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        files: FilesApi,
        writer: StepDraftWriter,
        create_course: CreateCourse,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files
        self.writer = writer
        self.create_course = create_course

    async def execute(
        self, actor: Actor, data: bytes, *, title: str | None = None
    ) -> ImportOutcome:
        """Import the cartridge as a new invite-only course with a draft only.

        Raises:
            ForbiddenError: Neither an LMS admin nor a course creator.
            CartridgeInvalidError: The archive is unsafe or not a cartridge.
            JobCancelled: The job was asked to stop.
        """
        actor.require(Role.LMS_ADMIN, Role.LMS_CREATOR)
        archive, plan = await asyncio.to_thread(_plan, data)
        total = len(plan.assets) + sum(len(s.steps) for s in plan.sections)
        await job_progress(done=0, total=total, note=plan.title)
        file_ids = await self._upload(actor, archive, plan, total)
        name = title or plan.title
        course = await self.create_course.execute(
            actor,
            title=name,
            slug=_slug(name),
            visibility=Visibility.INVITE,
        )
        await self._fill(actor, course.id, plan, file_ids, total)
        return ImportOutcome(course_id=course.id, report=plan.report)

    async def _upload(
        self, actor: Actor, archive: CartridgeArchive, plan: ImportPlan, total: int
    ) -> list[UUID]:
        ids: list[UUID] = []
        for index, path in enumerate(plan.assets):
            if await job_should_stop():
                raise JobCancelled()
            stored = await self.files.store_bytes(
                owner_id=actor.user_id,
                scope=FileScope.STAFF,
                purpose=FilePurpose.LINK,
                name=posixpath.basename(path)[:200] or "file",
                data=archive.read(path),
            )
            ids.append(stored.id)
            await job_progress(done=index + 1, total=total)
        return ids

    async def _fill(
        self,
        actor: Actor,
        course_id: UUID,
        plan: ImportPlan,
        file_ids: list[UUID],
        total: int,
    ) -> None:
        done = len(file_ids)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            ops = [AddSection(op="add_section", title=s.title) for s in plan.sections]
            outline, section_ids = apply_ops(
                course.draft_outline, ops, course_step_ids=()
            )
            for section, section_id in zip(plan.sections, section_ids, strict=True):
                for planned in section.steps:
                    if await job_should_stop():
                        raise JobCancelled()
                    blocks = _swap_assets(planned.blocks, file_ids)
                    content = _content(planned.title, blocks, plan.report)
                    step = await self._step(course_id, content, actor, now, plan)
                    await uow.steps.add(step)
                    outline = add_step(outline, section_id, step.id, None)
                    done += 1
                    await job_progress(done=done, total=total)
            if plan.description:
                course.draft_meta = {
                    **course.draft_meta,
                    "description": plan.description,
                }
                course.outline_hash = outline_hash(course.draft_meta, outline)
            record_draft_change(
                course, outline=outline, actor_id=actor.user_id, now=now
            )
            await uow.courses.save(course)
            await uow.commit()

    async def _step(
        self,
        course_id: UUID,
        content: StepContent,
        actor: Actor,
        now: Any,  # noqa: ANN401 - datetime
        plan: ImportPlan,
    ) -> CourseStep:
        try:
            prepared = await self.writer.prepare_new(content)
        except ContentInvalidError:
            plan.report.note(content.title, "step", "content too large, left empty")
            prepared = await self.writer.prepare_new(
                StepContent(title=content.title, blocks=[])
            )
        return CourseStep(
            id=new_id(),
            course_id=course_id,
            draft=prepared.content,
            draft_hash=prepared.content_hash,
            created_via=StepVia.UI,
            draft_updated_via=StepVia.UI,
            draft_updated_by=actor.user_id,
            draft_updated_at=now,
            file_ids=prepared.file_ids,
        )


def _plan(data: bytes) -> tuple[CartridgeArchive, ImportPlan]:
    archive = CartridgeArchive(data)
    return archive, plan_import(archive)


def _swap_assets(value: Any, file_ids: list[UUID]) -> Any:  # noqa: ANN401 - JSON
    if isinstance(value, str):
        return _ASSET.sub(lambda m: f"/files/{file_ids[int(m.group(1))]}", value)
    if isinstance(value, list):
        return [_swap_assets(v, file_ids) for v in value]
    if isinstance(value, dict):
        return {k: _swap_assets(v, file_ids) for k, v in value.items()}
    return value


def _content(
    title: str, blocks: list[dict[str, Any]], report: ImportReport
) -> StepContent:
    """Keep the blocks that validate; note the others."""
    valid: list[Any] = []
    for block in blocks:
        try:
            valid.append(_BLOCK.validate_python(block))
        except ValidationError:
            report.note(title, str(block.get("type", "block")), "block left out")
    return StepContent(title=title, blocks=valid)


def _slug(title: str) -> str:
    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    )
    base = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:40] or "course"
    return f"{base}-{secrets.token_hex(3)}"
