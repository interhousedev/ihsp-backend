"""Telegram messages of the built-in renderers (BOT-11–15, UF-BOT-04, UF-BOT-07)."""

from typing import Any

from app.modules.notify.application.renderers.builtin import register_builtin_renderers
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.factories.notify import make_resource, make_user
from tests.fakes.notify.files import FakeFilesApi
from tests.fakes.notify.links import FakeLinksApi

import pytest

URLS = UrlsSettings()
BOT_TYPES = {
    NotificationType.LESSON_PROMPT,
    NotificationType.MAIL,
    NotificationType.TELEGRAM_LINKED,
    NotificationType.OTP_RESET_REQUESTED,
}


class World:
    """A registry with the built-in renderers and the fakes behind it."""

    def __init__(self, i18n: I18nCore) -> None:
        self.links = FakeLinksApi()
        self.files = FakeFilesApi()
        self.registry = RendererRegistry()
        register_builtin_renderers(
            self.registry, i18n=i18n, urls=URLS, links=self.links, files=self.files
        )

    async def render(
        self,
        notification_type: NotificationType,
        payload: dict[str, Any],
        *,
        role: Role = Role.STUDENT,
        locale: str = "en",
    ) -> RenderedMessage | None:
        renderer = self.registry.get(notification_type)
        assert renderer is not None
        user = make_user(role, locale=locale)
        ctx = RenderContext(user=user, locale=locale, telegram_user_id=7)
        return await renderer(payload, ctx)


@pytest.fixture
def world(i18n: I18nCore) -> World:
    return World(i18n)


def test_every_type_except_the_bot_types_has_a_builtin_renderer(world: World) -> None:
    """BOT-11: B14 registers only lesson_prompt, mail, telegram_linked, otp_reset."""
    registered = {t for t in NotificationType if world.registry.get(t) is not None}

    assert registered == set(NotificationType) - BOT_TYPES


async def test_marks_message_has_open_grades_and_settings_buttons(world: World) -> None:
    """UF-BOT-04: one message per sync run with Open grades and settings."""
    payload = {
        "marks": [
            {
                "subject_id": "s1",
                "subject_name": "Mathematics",
                "value": 5,
                "type": "lesson",
                "date": "2026-10-06",
            },
            {
                "subject_id": "s2",
                "subject_name": "Physics",
                "value": 3,
                "type": "midterm",
                "date": "2026-10-06",
            },
        ],
        "result_changes": [
            {"subject_id": "s2", "subject_name": "Physics", "old": 4.21, "new": 3.95}
        ],
    }

    message = await world.render(NotificationType.MARKS, payload)

    assert message == RenderedMessage(
        text_html=(
            "<b>New marks</b>\n"
            "Mathematics — 5 (lesson), 06.10\n"
            "Physics — 3 (midterm), 06.10\n"
            "Semester mark: Physics 4.21 → 3.95"
        ),
        buttons=[
            [
                {"text": "Open grades", "web_app_url": f"{URLS.sp}/grades/"},
                {"text": "Notification settings", "callback_data": "m:settings"},
            ]
        ],
    )


async def test_values_from_payloads_are_html_escaped(world: World) -> None:
    """BOT-11: a subject name cannot inject markup into the message."""
    payload = {
        "marks": [
            {
                "subject_id": "s1",
                "subject_name": "Math <script>&",
                "value": 5,
                "type": "lesson",
                "date": "2026-10-06",
            }
        ],
        "result_changes": [],
    }

    message = await world.render(NotificationType.MARKS, payload)

    assert message is not None
    assert "Math &lt;script&gt;&amp;" in message.text_html
    assert "<script>" not in message.text_html


async def test_drop_alert_has_an_open_grades_button(world: World) -> None:
    """UF-BOT-05: 'GPA dropped: 4.62 → 4.55' with Open grades."""
    payload = {"scope": "gpa", "semester": 1, "old": 4.62, "new": 4.55}

    message = await world.render(NotificationType.RESULT_DROP, payload, locale="ru")

    assert message is not None
    assert message.text_html == (
        "<b>Результат снизился</b>\nСредний балл снизился: 4.62 → 4.55"
    )
    assert message.buttons == [
        [{"text": "Открыть оценки", "web_app_url": f"{URLS.sp}/grades/"}]
    ]


async def test_threshold_alert_names_the_subject(world: World) -> None:
    """UF-BOT-05: 'Physics semester mark is below 4.0'."""
    payload = {
        "scope": "subject",
        "subject_name": "Physics",
        "value": 3.9,
        "threshold": 4.0,
    }

    message = await world.render(NotificationType.RESULT_BELOW, payload)

    assert message is not None
    assert "Physics semester mark is below 4.00" in message.text_html


async def test_lesson_resources_message_matches_the_readme_example(
    world: World,
) -> None:
    """UF-BOT-07, BOT-15, ROOM-3: room page with PIN, materials and attachments."""
    lesson_id = new_id()
    world.links.resources[lesson_id] = [
        make_resource(lesson_id, role="material"),
        make_resource(
            lesson_id,
            role="attachment",
            title="Derivatives.pdf",
            short_url="https://s.ihsu.uz/T2_q8Wn5",
            author="Aleksey",
        ),
        make_resource(lesson_id, role="homework", title="Task.pdf"),
    ]
    payload = {
        "lesson_id": str(lesson_id),
        "group_names": ["2TN2"],
        "subject_name": "Physics",
        "period": 3,
        "room_name": "102",
        "room_url": "http://localhost:8000/r/102",
        "room_pin": "483920",
    }

    message = await world.render(NotificationType.LESSON_RESOURCES, payload)

    assert message == RenderedMessage(
        text_html=(
            "2TN2 · Physics · Period 3 · Room 102\n"
            "Room page: http://localhost:8000/r/102?pin=483920 (PIN 483920)\n"
            "Materials: https://s.ihsu.uz/9d-K4m_x (Lecture 5.pdf)\n"
            "Attachments:\n"
            "Aleksey - https://s.ihsu.uz/T2_q8Wn5 (Derivatives.pdf)"
        ),
        buttons=[
            [
                {
                    "text": "Open room page",
                    "url": "http://localhost:8000/r/102?pin=483920",
                },
                {
                    "text": "Open lesson",
                    "web_app_url": f"{URLS.sp}/lessons/view/?id={lesson_id}",
                },
            ]
        ],
    )


async def test_teachers_open_the_lesson_in_the_staff_portal(world: World) -> None:
    """BOT-15: the teacher's Open lesson button is a staff portal mini app."""
    lesson_id = new_id()
    world.links.resources[lesson_id] = [make_resource(lesson_id)]
    payload = {
        "lesson_id": str(lesson_id),
        "group_names": ["2TN2", "2TN3"],
        "subject_name": "Physics",
        "period": 3,
    }

    message = await world.render(
        NotificationType.LESSON_RESOURCES, payload, role=Role.TEACHER
    )

    assert message is not None
    assert message.text_html.splitlines()[0] == "2TN2, 2TN3 · Physics · Period 3"
    assert message.buttons == [
        [
            {
                "text": "Open lesson",
                "web_app_url": f"{URLS.staff}/lessons/view/?id={lesson_id}",
            }
        ]
    ]


async def test_lesson_without_visible_resources_sends_nothing(world: World) -> None:
    """UF-BOT-07 alternative 1a: no resources, no message."""
    lesson_id = new_id()
    world.links.resources[lesson_id] = [make_resource(lesson_id, hidden=True)]
    payload = {"lesson_id": str(lesson_id), "group_names": ["2TN2"], "period": 3}

    message = await world.render(NotificationType.LESSON_RESOURCES, payload)

    assert message is None


async def test_lesson_without_a_room_has_no_room_line_or_button(world: World) -> None:
    """UF-BOT-07 alternative 1b: no room, no room page line."""
    lesson_id = new_id()
    world.links.resources[lesson_id] = [make_resource(lesson_id)]
    payload = {
        "lesson_id": str(lesson_id),
        "group_names": ["2TN2"],
        "subject_name": "Physics",
        "period": 3,
    }

    message = await world.render(NotificationType.LESSON_RESOURCES, payload)

    assert message is not None
    assert "Room page" not in message.text_html
    assert [b["text"] for row in message.buttons or [] for b in row] == ["Open lesson"]


async def test_broadcast_message_has_bold_title_html_text_and_media(
    world: World,
) -> None:
    """BOT-21, ADM-11: title, formatted text and media sent as documents."""
    media = world.files.add("schedule.pdf", b"%PDF-1")
    payload = {
        "broadcast_id": str(new_id()),
        "title": "Exams <soon>",
        "text": "<b>Hi</b> all",
        "media_file_ids": [str(media.id)],
    }

    message = await world.render(NotificationType.BROADCAST, payload)

    assert message == RenderedMessage(
        text_html="<b>Exams &lt;soon&gt;</b>\n\n<b>Hi</b> all",
        documents=(("schedule.pdf", b"%PDF-1"),),
    )


async def test_missing_media_file_is_skipped(world: World) -> None:
    """BOT-21: a deleted file does not block the broadcast."""
    payload = {
        "title": "T",
        "text": "x",
        "media_file_ids": [str(new_id())],
    }

    message = await world.render(NotificationType.BROADCAST, payload)

    assert message is not None
    assert message.documents == ()


async def test_preview_is_marked(world: World) -> None:
    """UF-ADM-08 step 3: the preview says it is a preview."""
    payload = {"title": "T", "text": "x", "media_file_ids": [], "preview": True}

    message = await world.render(NotificationType.BROADCAST, payload, locale="ru")

    assert message is not None
    assert message.text_html.startswith("<i>Предпросмотр</i>\n<b>T</b>")


@pytest.mark.parametrize(
    ("notification_type", "payload", "button_text", "link"),
    [
        (
            NotificationType.EMIS_REAUTH,
            {},
            "Update EMIS password",
            f"{URLS.id}/security/emis/",
        ),
        (
            NotificationType.SYNC_ALERT,
            {"run_id": "r", "failed": 3, "total": 120},
            "Open monitoring",
            f"{URLS.admin}/monitoring/",
        ),
    ],
)
async def test_links_outside_the_mini_apps_are_url_buttons(
    world: World,
    notification_type: NotificationType,
    payload: dict[str, Any],
    button_text: str,
    link: str,
) -> None:
    """BOT-8: only IHSP Web and the staff portal open as mini apps."""
    message = await world.render(notification_type, payload)

    assert message is not None
    assert message.buttons == [[{"text": button_text, "url": link}]]


async def test_notifications_without_a_page_have_no_buttons(world: World) -> None:
    """BOT-11: plain information messages carry no buttons."""
    message = await world.render(
        NotificationType.ACCOUNT_CLOSING, {"closes_on": "2026-11-01"}
    )

    assert message is not None
    assert message.buttons is None
    assert (
        message.text_html
        == "<b>Account closing</b>\nYour account will be closed on 01.11."
    )


async def test_ready_notebook_output_opens_the_artifact_as_a_mini_app(
    world: World,
) -> None:
    """NB-21: bold title, kind and title of the output, and an Open notebook button."""
    notebook_id, artifact_id = new_id(), new_id()
    payload = {
        "notebook_id": str(notebook_id),
        "artifact_id": str(artifact_id),
        "kind": "quiz",
        "title": "Cells <1> & tissues",
    }

    message = await world.render(NotificationType.NOTEBOOK_ARTIFACT_READY, payload)

    assert message == RenderedMessage(
        text_html=(
            "<b>Notebook output is ready</b>\n"
            "Ready: Quiz “Cells &lt;1&gt; &amp; tissues”"
        ),
        buttons=[
            [
                {
                    "text": "Open notebook",
                    "web_app_url": (
                        f"{URLS.sp}/notebooks/view/"
                        f"?id={notebook_id}&artifact={artifact_id}"
                    ),
                }
            ]
        ],
    )


async def test_ready_notebook_output_is_rendered_in_the_language_of_the_reader(
    world: World,
) -> None:
    """NB-21: the message and the button follow the locale of the account."""
    payload = {
        "notebook_id": str(new_id()),
        "artifact_id": str(new_id()),
        "kind": "report",
        "title": "Клетка",
    }

    message = await world.render(
        NotificationType.NOTEBOOK_ARTIFACT_READY, payload, locale="ru"
    )

    assert message is not None
    assert message.text_html == (
        "<b>Материал блокнота готов</b>\nГотово: Отчёт «Клетка»"
    )
    assert [b["text"] for row in message.buttons or [] for b in row] == [
        "Открыть блокнот"
    ]


async def test_lesson_absence_has_an_attendance_button(i18n: I18nCore) -> None:
    """The student gets a mini app button to the attendance page."""
    message = await World(i18n).render(
        NotificationType.LESSON_ABSENCE,
        {
            "date": "2026-10-06",
            "period": 3,
            "subject_name": "Physics",
            "teacher_name": "Rustamov Aziz",
            "update": False,
        },
    )

    assert message is not None
    assert message.buttons == [
        [{"text": "Open attendance", "web_app_url": f"{URLS.sp}/attendance/"}]
    ]


async def test_curator_absences_has_an_attendance_button(i18n: I18nCore) -> None:
    """The curator gets a button to the group attendance page."""
    message = await World(i18n).render(
        NotificationType.CURATOR_ABSENCES,
        {"date": "2026-10-06", "group_name": "2TN2", "items": []},
        role=Role.TEACHER,
    )

    assert message is not None
    assert message.buttons == [
        [{"text": "Open attendance", "web_app_url": f"{URLS.staff}/group/attendance/"}]
    ]


async def test_teacher_temporary_marks_has_a_button(i18n: I18nCore) -> None:
    """The teacher gets a button to the temporary marks page."""
    message = await World(i18n).render(
        NotificationType.TEACHER_TEMPORARY_MARKS,
        {"date": "2026-10-20", "count": 0, "items": []},
        role=Role.TEACHER,
    )

    assert message is not None
    assert message.buttons == [
        [
            {
                "text": "Open temporary marks",
                "web_app_url": f"{URLS.staff}/temporary-marks/",
            }
        ]
    ]
