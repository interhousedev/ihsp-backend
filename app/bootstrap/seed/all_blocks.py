"""Demo course with one lesson for every LMS block type (the Duo line check)."""

from typing import Any
from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.seed.content import (
    CARDS,
    COURSE_SLUG,
    LESSON_TEXT,
    QUESTIONS,
)
from app.bootstrap.seed.library import STUDENT_LOGIN
from app.interfaces.mcp.lms.blocks import (
    build_flashcards_block,
    build_question,
    build_test_block,
    build_text_block,
)
from app.modules.lms.domain.authoring.enums import Visibility
from app.modules.lms.domain.authoring.errors import SlugTakenError
from app.shared.actor import Actor, Role

import structlog

log = structlog.get_logger(__name__)

ALL_BLOCKS_SLUG = "demo-all-blocks"
ALL_BLOCKS_TITLE = "Демо: все типы уроков"
VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _exam() -> dict[str, Any]:
    questions = [build_question(q) for q in QUESTIONS[:2]]
    return {
        "type": "exam",
        "title": "Контрольная работа",
        "kind": "custom",
        "calculator": "none",
        "sections": [
            {
                "title": "Раздел 1",
                "modules": [
                    {"title": "Модуль 1", "time_limit_sec": 600, "questions": questions}
                ],
            }
        ],
    }


def _stages() -> list[tuple[str, list[tuple[str, dict[str, Any]]]]]:
    """Sections with their lessons, each lesson holding one block."""
    return [
        (
            "Чтение и практика",
            [
                ("Теория: уравнения", build_text_block(LESSON_TEXT)),
                ("Тест: уравнения", build_test_block(None, QUESTIONS)),
                ("Карточки: термины", build_flashcards_block(CARDS)),
            ],
        ),
        (
            "Видео и интерактив",
            [
                (
                    "Видео: падение тела",
                    {"type": "video", "source": "link", "url": VIDEO_URL},
                ),
                (
                    "Интерактивное видео: падение тела",
                    {
                        "type": "interactive_video",
                        "source": "link",
                        "url": VIDEO_URL,
                        "interactions": [
                            {"at_sec": 5, "kind": "note", "text": "Pay attention."},
                            {
                                "at_sec": 10,
                                "kind": "question",
                                "text": "2 + 2?",
                                "options": [
                                    {"text": "4", "correct": True},
                                    {"text": "5"},
                                ],
                            },
                        ],
                    },
                ),
                (
                    "Интерактив: соотнеси понятия",
                    {"type": "h5p", "title": "Соотнеси понятия"},
                ),
                (
                    "Падение тела: модель",
                    {"type": "html", "title": "Падение тела: модель"},
                ),
            ],
        ),
        (
            "Проверка знаний",
            [
                ("Контрольная работа", _exam()),
                (
                    "Программирование: вывод числа",
                    {
                        "type": "code",
                        "language": "python",
                        "instructions": "Print 42.",
                        "starter": "print(0)\n",
                        "solution": "print(42)\n",
                        "tests": [{"name": "prints 42", "code": "print(42)"}],
                    },
                ),
                (
                    "Проверка проекта с ИИ",
                    {
                        "type": "ai_review",
                        "title": "Проверка проекта",
                        "instructions_public": "Upload your project.",
                        "teacher_prompt": "Review the work against the criteria.",
                        "criteria": [{"name": "Clarity", "max_score": 10}],
                    },
                ),
            ],
        ),
    ]


async def seed_all_blocks_course(container: Container, admin_id: UUID) -> None:
    """Create and publish the all-block-types course (once)."""
    authoring = container.lms.authoring
    actor = Actor(user_id=admin_id, roles=frozenset({Role.ADMIN, Role.LMS_ADMIN}))
    try:
        course = await authoring.create_course.execute(
            actor,
            title=ALL_BLOCKS_TITLE,
            slug=ALL_BLOCKS_SLUG,
            visibility=Visibility.PUBLIC,
        )
    except SlugTakenError:
        await _retitle_existing(container, actor)
        return
    commands = authoring.draft_commands
    for section_title, lessons in _stages():
        section = await commands.create_section(
            actor, course.id, section_title, via_mcp=False
        )
        for title, block in lessons:
            step = await commands.create_step(
                actor, course.id, section["id"], title, via_mcp=False
            )
            await commands.add_block(actor, UUID(step["step_id"]), block, via_mcp=False)
    draft = await authoring.get_course_draft.execute(actor, course.id)
    await authoring.publish_course.execute(
        actor, course.id, draft_seq=draft.draft_seq, note="First version"
    )
    log.info("seed_course_published", slug=ALL_BLOCKS_SLUG)


async def _retitle_existing(container: Container, actor: Actor) -> None:
    """Bring section and step titles of an already seeded course up to date."""
    authoring = container.lms.authoring
    commands = authoring.draft_commands
    page = await container.lms.learning.get_course_page.execute(actor, ALL_BLOCKS_SLUG)
    draft = await authoring.get_course_draft.execute(actor, page.id)
    changed = False
    for section, (section_title, lessons) in zip(draft.outline, _stages()):
        if section.title != section_title:
            await commands.update_module(actor, page.id, section.id, section_title)
            changed = True
        for step, (title, _block) in zip(section.steps, lessons):
            if step.title != title:
                await commands.update_step(
                    actor, step.step_id, title=title, blocks=None
                )
                changed = True
    if not changed:
        return
    draft = await authoring.get_course_draft.execute(actor, page.id)
    await authoring.publish_course.execute(
        actor, page.id, draft_seq=draft.draft_seq, note="Lesson titles"
    )
    log.info("seed_course_retitled", slug=ALL_BLOCKS_SLUG)


async def enrol_demo_student(container: Container) -> None:
    """Enrol the demo student in the demo courses (once each)."""
    user = await container.identity.directory.user_by_login(STUDENT_LOGIN)
    if user is None:
        return
    learning = container.lms.learning
    student = Actor(user_id=user.id, roles=frozenset({Role.STUDENT}))
    for slug in (COURSE_SLUG, ALL_BLOCKS_SLUG):
        page = await learning.get_course_page.execute(student, slug)
        async with learning.enroll_in_course.uow_factory() as uow:
            if await uow.enrollments.get(page.id, user.id) is None:
                await uow.enrollments.add(
                    course_id=page.id, user_id=user.id, via="self"
                )
                await uow.commit()
