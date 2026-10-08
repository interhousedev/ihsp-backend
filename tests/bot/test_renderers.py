"""Renderers the bot registers for the notification registry (FINAL_PLAN B14 step 5)."""

from datetime import UTC, datetime

from app.interfaces.bot.renderers import _moment, register_bot_renderers
from app.shared.base_error import ForbiddenError
from app.shared.contracts.callbacks import AttToggleCb, OtpCancelCb
from app.shared.contracts.notify import RenderContext, Renderer
from app.shared.ids import new_id, uuid_to_b64
from app.shared.notifications import NotificationType
from tests.bot.support.fakes import (
    STUDENT_TG,
    TEACHER_TG,
    World,
    make_file_ref,
    make_mail,
)

import pytest


class Registry:
    """The notification renderer registry, reduced to what the bot needs."""

    def __init__(self) -> None:
        """Start empty."""
        self.renderers: dict[NotificationType, Renderer] = {}

    def register(self, type_: NotificationType, renderer: Renderer, /) -> None:
        """Store the renderer."""
        self.renderers[type_] = renderer


@pytest.fixture
def registry(world: World) -> Registry:
    """A registry with the bot's renderers."""
    registry = Registry()
    register_bot_renderers(registry, world.container)
    return registry


def student_ctx(world: World) -> RenderContext:
    """Rendering for the student's Telegram account."""
    return RenderContext(user=world.student, locale="en", telegram_user_id=STUDENT_TG)


def teacher_ctx(world: World) -> RenderContext:
    """Rendering for the teacher's Telegram account."""
    return RenderContext(user=world.teacher, locale="en", telegram_user_id=TEACHER_TG)


def labels(buttons: list[list[dict[str, object]]] | None) -> list[object]:
    """Flat button labels."""
    return [button["text"] for row in buttons or [] for button in row]


def test_the_bot_registers_exactly_its_four_renderers(registry: Registry) -> None:
    """FINAL_PLAN B14: lesson_prompt, mail, telegram_linked, otp_reset_requested."""
    assert set(registry.renderers) == {
        NotificationType.LESSON_PROMPT,
        NotificationType.MAIL,
        NotificationType.TELEGRAM_LINKED,
        NotificationType.OTP_RESET_REQUESTED,
    }


async def test_lesson_prompt_renders_the_checklist(
    world: World, registry: Registry
) -> None:
    """BOT-16: the prompt is the attendance checklist with the lesson header."""
    lesson = world.classwork.state["lesson"]
    payload = {"lesson_id": str(lesson.id), "teacher_id": str(world.teacher.id)}

    message = await registry.renderers[NotificationType.LESSON_PROMPT](
        payload, teacher_ctx(world)
    )

    assert message is not None
    assert message.text_html.splitlines()[0] == (
        "<b>bot-prompt-ends-in[minutes=5,title=2TN2 · Physics]</b>"
    )
    assert labels(message.buttons)[:3] == ["Alice", "Bob", "Carol"]
    assert message.buttons is not None
    expected = AttToggleCb(lesson=uuid_to_b64(lesson.id), pos=0).pack()
    assert message.buttons[0][0]["callback_data"] == expected


async def test_lesson_prompt_is_skipped_when_expired_or_done(
    world: World, registry: Registry
) -> None:
    """No prompt for an expired lesson or when everything was done on the web."""
    render = registry.renderers[NotificationType.LESSON_PROMPT]
    payload = {"lesson_id": str(world.classwork.state["lesson"].id)}

    world.classwork.state["expired"] = True
    assert await render(payload, teacher_ctx(world)) is None

    world.classwork.state["expired"] = False
    world.classwork.state["attendance_submitted"] = True
    world.classwork.state["homework_text"] = "done on the web"
    assert await render(payload, teacher_ctx(world)) is None


async def test_lesson_prompt_is_skipped_for_a_reassigned_lesson(
    world: World, registry: Registry
) -> None:
    """UF-BOT-08: a teacher who lost the lesson gets nothing."""
    world.classwork.prompt_error = ForbiddenError()
    payload = {"lesson_id": str(world.classwork.state["lesson"].id)}

    result = await registry.renderers[NotificationType.LESSON_PROMPT](
        payload, teacher_ctx(world)
    )

    assert result is None


async def test_mail_renders_the_email_and_its_attachments_as_documents(
    world: World, registry: Registry
) -> None:
    """MAIL-2: sender, subject, body and attachments as documents."""
    attachment = make_file_ref("notes.pdf", 10, world.student.id)
    mail = world.mail.add(make_mail("Exam"), attachments=[attachment])
    world.files.contents[attachment.id] = b"pdf-bytes"

    message = await registry.renderers[NotificationType.MAIL](
        {"mail_id": str(mail.id)}, student_ctx(world)
    )

    assert message is not None
    assert message.text_html.startswith("<b>Exam</b>")
    assert message.documents == (("notes.pdf", b"pdf-bytes"),)
    assert labels(message.buttons) == [
        "bot-btn-reply",
        "bot-btn-forward",
        "bot-btn-spam",
    ]


async def test_mail_attachment_over_50_mb_is_named_not_sent(
    world: World, registry: Registry
) -> None:
    """MAIL-2: attachments over 50 MB are skipped with a note."""
    big = make_file_ref("movie.mp4", 60_000_000, world.student.id)
    mail = world.mail.add(make_mail("Video"), attachments=[big])

    message = await registry.renderers[NotificationType.MAIL](
        {"mail_id": str(mail.id)}, student_ctx(world)
    )

    assert message is not None
    assert message.documents == ()
    assert "bot-mail-attachment-skipped[name=movie.mp4]" in message.text_html


async def test_a_long_email_is_cut_to_fit_and_gets_show_full(
    world: World, registry: Registry
) -> None:
    """MAIL-2: a body that does not fit is cut and Show full appears."""
    mail = world.mail.add(make_mail("Long"), html_telegram="x" * 6000)

    message = await registry.renderers[NotificationType.MAIL](
        {"mail_id": str(mail.id)}, student_ctx(world)
    )

    assert message is not None
    assert len(message.text_html) < 4096
    assert "bot-btn-full" in labels(message.buttons)


async def test_telegram_linked_greets_the_linked_account_with_the_menu(
    world: World, registry: Registry
) -> None:
    """UF-BOT-01 step 6: "Logged in as ..." and the main menu."""
    payload = {"telegram_user_id": STUDENT_TG, "telegram_username": "student"}

    message = await registry.renderers[NotificationType.TELEGRAM_LINKED](
        payload, student_ctx(world)
    )

    assert message is not None
    assert message.text_html.startswith("bot-linked-as[login=brastilov.aleksey")
    assert message.buttons is not None
    assert message.buttons[0][0]["callback_data"] == "m:today"


async def test_telegram_linked_tells_other_accounts_with_a_security_link(
    world: World, registry: Registry
) -> None:
    """UF-BOT-01 step 5: other channels get "was linked" with Not me."""
    payload = {"telegram_user_id": 999, "telegram_username": "newone"}

    message = await registry.renderers[NotificationType.TELEGRAM_LINKED](
        payload, student_ctx(world)
    )

    assert message is not None
    assert message.text_html == "bot-linked-elsewhere[who=@newone]"
    assert message.buttons == [
        [{"text": "bot-btn-security", "url": "http://localhost:3001/security/"}]
    ]


async def test_otp_reset_notice_carries_the_cancel_button(
    world: World, registry: Registry
) -> None:
    """The notice gets OtpCancelCb with the packed request id, time in Tashkent."""
    request_id = new_id()
    payload = {
        "effective_at": "2026-10-07T09:00:00+00:00",
        "request_id": str(request_id),
    }

    message = await registry.renderers[NotificationType.OTP_RESET_REQUESTED](
        payload, student_ctx(world)
    )

    assert message is not None
    assert message.text_html == "bot-otp-reset[when=07.10 14:00]"
    assert message.buttons == [
        [
            {
                "text": "bot-btn-otp-cancel",
                "callback_data": OtpCancelCb(request=uuid_to_b64(request_id)).pack(),
            }
        ]
    ]


def test_a_payload_time_without_a_zone_is_taken_as_utc() -> None:
    """Payload times are ISO strings; a naive one is UTC."""
    assert _moment("2026-10-07T09:00:00") == datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
