"""Demo content: an LMS course, a student's flash cards and a broadcast draft."""

from typing import Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.mcp.cards import FlashcardInput
from app.interfaces.mcp.lms.blocks import (
    build_flashcards_block,
    build_test_block,
    build_text_block,
)
from app.interfaces.mcp.lms.inputs import OptionInput, QuestionInput
from app.modules.admin.domain.audience import Audience
from app.modules.admin.domain.broadcast import BroadcastStatus, CreatedVia
from app.modules.lms.domain.authoring.enums import Visibility
from app.modules.lms.domain.authoring.errors import SlugTakenError
from app.shared.actor import Actor, Role

import structlog

log = structlog.get_logger(__name__)

COURSE_SLUG = "derivatives-101"
COURSE_TITLE = "Derivatives 101"
BROADCAST_TITLE = "Welcome to IHSP"
FLASHCARD_SET_TITLE = "Derivative rules"

LESSON_TEXT = (
    "# What is a derivative?\n\n"
    "The derivative of a function measures how fast it changes. For "
    "$f(x) = x^2$ the derivative is $f'(x) = 2x$.\n\n"
    "Rules to remember:\n\n- $(c)' = 0$\n- $(x^n)' = n x^{n-1}$\n"
    "- $(f + g)' = f' + g'$\n"
)

CARDS = [
    FlashcardInput(front="(c)'", back="0"),
    FlashcardInput(front="(x^n)'", back="n x^(n-1)"),
    FlashcardInput(front="(sin x)'", back="cos x"),
    FlashcardInput(front="(e^x)'", back="e^x"),
]


def _single(prompt: str, right: str, wrong: list[str]) -> QuestionInput:
    options = [OptionInput(text=right, correct=True)]
    options += [OptionInput(text=text) for text in wrong]
    return QuestionInput(type="single", prompt=prompt, options=options)


QUESTIONS = [
    _single("What is the derivative of x^2?", "2x", ["x", "x^2", "2"]),
    _single("What is the derivative of a constant?", "0", ["1", "the constant", "x"]),
    QuestionInput(
        type="multiple",
        prompt="Which of these are rules of differentiation?",
        options=[
            OptionInput(text="Sum rule", correct=True),
            OptionInput(text="Product rule", correct=True),
            OptionInput(text="Pythagorean rule"),
        ],
    ),
    QuestionInput(type="number", prompt="Value of (3x)' at any x?", number=3.0),
    QuestionInput(
        type="text",
        prompt="Name the derivative of sin x.",
        accepted_answers=["cos x", "cos(x)", "cosx"],
    ),
]


async def seed_course(container: Container, admin_id: UUID) -> UUID | None:
    """Create and publish "Derivatives 101"; return None when it already exists."""
    authoring = container.lms.authoring
    actor = Actor(user_id=admin_id, roles=frozenset({Role.ADMIN, Role.LMS_ADMIN}))
    try:
        course = await authoring.create_course.execute(
            actor, title=COURSE_TITLE, slug=COURSE_SLUG, visibility=Visibility.PUBLIC
        )
    except SlugTakenError:
        return None
    commands = authoring.draft_commands
    section = await commands.create_section(actor, course.id, "Basics", via_mcp=False)
    blocks: list[tuple[str, dict[str, Any]]] = [
        ("What is a derivative", build_text_block(LESSON_TEXT)),
        ("Check yourself", build_test_block(None, QUESTIONS)),
        ("Flash cards", build_flashcards_block(CARDS)),
    ]
    for title, block in blocks:
        step = await commands.create_step(
            actor, course.id, section["id"], title, via_mcp=False
        )
        await commands.add_block(actor, UUID(step["step_id"]), block, via_mcp=False)
    draft = await authoring.get_course_draft.execute(actor, course.id)
    await authoring.publish_course.execute(
        actor, course.id, draft_seq=draft.draft_seq, note="First version"
    )
    log.info("seed_course_published", slug=COURSE_SLUG)
    return course.id


async def seed_flashcards(container: Container, owner_id: UUID) -> None:
    """A flash card set for a demo student (once)."""
    api = container.flashcards.public
    if any(s["title"] == FLASHCARD_SET_TITLE for s in await api.list_sets(owner_id)):
        return
    await api.create_set(
        owner_id,
        FLASHCARD_SET_TITLE,
        [(card.front, card.back) for card in CARDS],
        source="manual",
    )


async def seed_broadcast(container: Container, admin_id: UUID) -> None:
    """A broadcast draft for everyone (once); it is never sent by the seed."""
    actor = Actor(user_id=admin_id, roles=frozenset({Role.ADMIN}))
    page = await container.admin.list_broadcasts.execute(
        actor, status=BroadcastStatus.DRAFT, limit=50
    )
    if any(item.broadcast.title == BROADCAST_TITLE for item in page.items):
        return
    await container.admin.create_broadcast.execute(
        actor,
        title=BROADCAST_TITLE,
        text="Welcome! This is a demo broadcast draft.",
        media_file_ids=[],
        audience=Audience(everyone=True),
        created_via=CreatedVia.UI,
    )
