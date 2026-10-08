"""BOT-20, BOT-23, UF-BOT-09: a teacher adds a lesson resource from Telegram."""

from datetime import timedelta

from app.shared.contracts.academic import LessonRef
from app.shared.contracts.callbacks import ResourceLessonCb
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.ids import uuid_to_b64
from tests.bot.support.fakes import NOW, STUDENT_TG, TEACHER_TG, make_lesson
from tests.bot.support.harness import Harness

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetFile

MB = 1000 * 1000


def tomorrow_lesson() -> LessonRef:
    """A lesson that has not started yet."""
    return make_lesson(
        subject_name="Chemistry",
        starts_at=NOW + timedelta(days=1),
        ends_at=NOW + timedelta(days=1, hours=1),
    )


async def test_document_over_20_mb_is_refused_with_a_staff_portal_link(
    harness: Harness,
) -> None:
    """UF-BOT-09 alternative 4a: bigger files go through the staff portal."""
    await harness.send_document(user_id=TEACHER_TG, file_size=21 * MB)

    assert harness.last_text() == "bot-resource-too-large"
    link = harness.last_buttons()[0][0]
    assert link.web_app is not None
    assert link.web_app.url == "http://localhost:3003"
    assert await harness.state_of(TEACHER_TG) is None


async def test_document_offers_todays_and_upcoming_lessons(harness: Harness) -> None:
    """BOT-23: a file from a teacher first asks "Add to a lesson?"."""
    running, later = make_lesson(), tomorrow_lesson()
    harness.world.schedule.teacher_lessons = [later, running]

    await harness.send_document(user_id=TEACHER_TG)

    assert harness.last_text() == "bot-resource-pick"
    callbacks = harness.last_callbacks()
    assert (
        ResourceLessonCb(lesson=uuid_to_b64(running.id), role="m").pack() in callbacks
    )
    assert ResourceLessonCb(lesson=uuid_to_b64(later.id), role="a").pack() in callbacks
    assert callbacks.index(
        ResourceLessonCb(lesson=uuid_to_b64(running.id), role="m").pack()
    ) < callbacks.index(ResourceLessonCb(lesson=uuid_to_b64(later.id), role="m").pack())


async def test_choosing_a_lesson_uploads_the_file_and_attaches_it(
    harness: Harness,
) -> None:
    """UF-BOT-09 steps 3-5: download, store, add the resource, confirm."""
    lesson = make_lesson()
    world = harness.world
    world.schedule.teacher_lessons = [lesson]
    harness.session.download_data = b"%PDF-data"
    await harness.send_document(user_id=TEACHER_TG, file_name="Lecture 5.pdf")

    await harness.press(
        ResourceLessonCb(lesson=uuid_to_b64(lesson.id), role="m").pack(),
        user_id=TEACHER_TG,
    )

    (stored,) = world.files.stored
    assert stored["data"] == b"%PDF-data"
    assert stored["ref"].name == "Lecture 5.pdf"
    assert stored["ref"].scope == FileScope.STAFF
    assert stored["ref"].purpose == FilePurpose.LINK
    (added,) = world.links.added
    assert added["role"] == "material"
    assert added["file_id"] == stored["ref"].id
    assert added["lesson_id"] == lesson.id
    assert "https://s.ihsu.uz/abc123" in harness.last_text()
    assert harness.last_buttons()[0][0].text == "bot-btn-open-lesson"
    assert await harness.state_of(TEACHER_TG) is None


async def test_a_link_is_attached_as_an_attachment(harness: Harness) -> None:
    """BOT-20: a URL goes through the same flow, as Attachment."""
    lesson = make_lesson()
    harness.world.schedule.teacher_lessons = [lesson]
    await harness.send("https://example.com/slides", user_id=TEACHER_TG)

    await harness.press(
        ResourceLessonCb(lesson=uuid_to_b64(lesson.id), role="a").pack(),
        user_id=TEACHER_TG,
    )

    (added,) = harness.world.links.added
    assert added["role"] == "attachment"
    assert added["url"] == "https://example.com/slides"
    assert added["file_id"] is None
    assert not harness.world.files.stored


async def test_no_lessons_in_the_window_says_so(harness: Harness) -> None:
    """UF-BOT-09 alternative 2a: "No lessons to attach to"."""
    await harness.send("https://example.com", user_id=TEACHER_TG)

    assert harness.last_text() == "bot-resource-no-lessons"
    assert await harness.state_of(TEACHER_TG) is None


async def test_add_resource_from_current_lesson_then_pick_the_role(
    harness: Harness,
) -> None:
    """BOT-20: Current lesson -> Add resource asks for the file, then the role only."""
    lesson = make_lesson()
    harness.world.schedule.teacher_lessons = [lesson]
    encoded = uuid_to_b64(lesson.id)

    await harness.press(
        ResourceLessonCb(lesson=encoded, role="p").pack(), user_id=TEACHER_TG
    )
    assert harness.sent[-1].text == "bot-resource-ask"

    await harness.send_document(user_id=TEACHER_TG)

    assert "bot-resource-role" in harness.last_text()
    assert harness.last_callbacks()[:2] == [
        ResourceLessonCb(lesson=encoded, role="m").pack(),
        ResourceLessonCb(lesson=encoded, role="a").pack(),
    ]


async def test_telegram_refusing_a_big_download_is_reported(harness: Harness) -> None:
    """File size can be missing from the update; Telegram then refuses the download."""
    lesson = make_lesson()
    harness.world.schedule.teacher_lessons = [lesson]
    await harness.send_document(user_id=TEACHER_TG, file_size=0)
    harness.session.queue(
        GetFile,
        TelegramBadRequest(
            method=GetFile(file_id="x"), message="Bad Request: file is too big"
        ),
    )

    await harness.press(
        ResourceLessonCb(lesson=uuid_to_b64(lesson.id), role="m").pack(),
        user_id=TEACHER_TG,
    )

    assert harness.last_text() == "bot-resource-too-large"
    assert not harness.world.links.added


async def test_pending_content_is_lost_after_the_state_expired(
    harness: Harness,
) -> None:
    """A resource button without a pending file is answered, not crashed."""
    lesson = make_lesson()

    await harness.press(
        ResourceLessonCb(lesson=uuid_to_b64(lesson.id), role="m").pack(),
        user_id=TEACHER_TG,
    )

    assert harness.toasts[-1].text == "bot-stale-button"
    assert not harness.world.links.added


async def test_students_sending_files_get_the_hint(harness: Harness) -> None:
    """Only teachers can add resources; a student gets the generic hint."""
    await harness.send_document(user_id=STUDENT_TG)

    assert harness.last_text().startswith("bot-hint-unexpected")
    assert not harness.world.files.stored
