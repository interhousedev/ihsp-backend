"""Builders and shortcuts shared by the authoring tests."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.views import (
    StepDraftView,
    VersionItemView,
)
from app.modules.lms.domain.step_content import StepContent
from app.modules.lms.infrastructure.orm import CourseStep as StepRow
from app.modules.lms.infrastructure.orm import StepRevision as RevisionRow
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.actor import Actor

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def text_block(markdown: str = "Hello") -> dict[str, Any]:
    """A Markdown block without an ID (the server assigns it)."""
    return {"type": "text", "markdown": markdown}


def single_question(prompt: str = "(x²)′ = ?") -> dict[str, Any]:
    """A single choice question with one correct option and one pinned option."""
    return {
        "type": "single",
        "prompt": prompt,
        "points": 1,
        "explanation": "Power rule.",
        "options": [
            {"text": "2x", "correct": True},
            {"text": "x", "correct": False},
            {"text": "None of the above", "correct": False, "pinned": True},
        ],
    }


def quiz_block(*questions: dict[str, Any]) -> dict[str, Any]:
    """A test block with the given questions."""
    return {
        "type": "test",
        "config": {"max_attempts": 3, "passing_score_pct": 60},
        "questions": list(questions),
    }


def cards_block() -> dict[str, Any]:
    """A flash cards block with one card."""
    return {"type": "flashcards", "cards": [{"front": "Power rule", "back": "n·xⁿ⁻¹"}]}


def content_of(title: str, *blocks: dict[str, Any]) -> StepContent:
    """Step content from raw blocks."""
    return StepContent.model_validate({"title": title, "blocks": list(blocks)})


async def set_blocks(
    services: AuthoringServices,
    actor: Actor,
    step: StepDraftView,
    *blocks: dict[str, Any],
    title: str | None = None,
) -> StepDraftView:
    """Replace the blocks of a step (as the editor does) and return the new draft."""
    content = content_of(title or step.content.title, *blocks)
    return await services.save_step_draft.execute(
        actor, step.step_id, content, step.lock_version
    )


async def publish(
    services: AuthoringServices, actor: Actor, course_id: UUID, note: str | None = None
) -> VersionItemView:
    """Review the pending changes and publish them."""
    pending = await services.get_pending_changes.execute(actor, course_id)
    return await services.publish_course.execute(
        actor, course_id, draft_seq=pending.draft_seq, note=note
    )


@dataclass(slots=True)
class Seeded:
    """A published course: one section with two steps, version 1."""

    section_id: str
    step_a: StepDraftView
    step_b: StepDraftView
    version: VersionItemView


async def seed_published(
    services: AuthoringServices, actor: Actor, course_id: UUID
) -> Seeded:
    """Create a section with steps A and B, fill them and publish version 1."""
    section = await services.create_section.execute(actor, course_id, "Limits")
    a = await services.create_step.execute(
        actor, course_id, section_id=section.id, title="Step A"
    )
    b = await services.create_step.execute(
        actor, course_id, section_id=section.id, title="Step B"
    )
    a = await set_blocks(services, actor, a, text_block("A1"))
    b = await set_blocks(
        services, actor, b, text_block("B1"), quiz_block(single_question())
    )
    version = await publish(services, actor, course_id, note="First version")
    return Seeded(section.id, a, b, version)


async def step_row(
    sessionmaker: async_sessionmaker[AsyncSession], step_id: UUID
) -> StepRow:
    """Read a step row straight from the database."""
    async with sessionmaker() as session:
        row = (
            await session.scalars(
                select(StepRow)
                .where(StepRow.id == step_id)
                .execution_options(populate_existing=True)
            )
        ).one()
        return row


async def revisions_of(
    sessionmaker: async_sessionmaker[AsyncSession], step_id: UUID
) -> Sequence[RevisionRow]:
    """Every stored revision of a step."""
    async with sessionmaker() as session:
        rows = await session.scalars(
            select(RevisionRow)
            .where(RevisionRow.step_id == step_id)
            .order_by(RevisionRow.created_at, RevisionRow.id)
            .execution_options(populate_existing=True)
        )
        return rows.all()


async def count_revisions(
    sessionmaker: async_sessionmaker[AsyncSession], step_id: UUID
) -> int:
    """Number of stored revisions of a step."""
    async with sessionmaker() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(RevisionRow)
            .where(RevisionRow.step_id == step_id)
        )
        return int(total or 0)
