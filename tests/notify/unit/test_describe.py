"""Web descriptions of notifications (WEB-27, UF-WEB-15)."""

from typing import Any

from app.modules.notify.application.describe import describe
from app.settings import UrlsSettings
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.notifications import NotificationType

import pytest

URLS = UrlsSettings()
LESSON_ID = str(new_id())
NOTEBOOK_ID = str(new_id())
ARTIFACT_ID = str(new_id())
ASSESSMENT_ID = str(new_id())
ITEM_ID = str(new_id())
LIST_ID = str(new_id())

PAYLOADS: dict[NotificationType, dict[str, Any]] = {
    NotificationType.MARKS: {
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
    },
    NotificationType.RESULT_DROP: {
        "scope": "gpa",
        "semester": 1,
        "old": 4.62,
        "new": 4.55,
    },
    NotificationType.RESULT_BELOW: {
        "scope": "subject",
        "subject_name": "Physics",
        "value": 3.9,
        "threshold": 4.0,
    },
    NotificationType.LESSON_RESOURCES: {
        "lesson_id": LESSON_ID,
        "group_names": ["2TN2"],
        "subject_name": "Physics",
        "period": 3,
        "room_name": "102",
    },
    NotificationType.LESSON_PROMPT: {
        "lesson_id": LESSON_ID,
        "teacher_id": "t",
        "ends_at": "2026-10-06T09:10:00+00:00",
    },
    NotificationType.LESSON_CHANGED: {
        "lesson_id": LESSON_ID,
        "date": "2026-10-07",
        "period": 2,
        "subject_name": "Physics",
        "changes": {"room": ["102", "204"], "teacher": [None, "Kalandarova G."]},
    },
    NotificationType.MAIL: {"mail_id": "m"},
    NotificationType.MAIL_BOUNCED: {"mail_id": "m", "to": "x@example.com"},
    NotificationType.BROADCAST: {
        "broadcast_id": "b",
        "title": "Exams",
        "text": "<b>Exams</b> start<br>on Monday &amp; Tuesday",
    },
    NotificationType.EMIS_REAUTH: {},
    NotificationType.FILES_EXPIRING: {
        "term_id": "t",
        "expires_on": "2027-01-15",
        "files_count": 4,
    },
    NotificationType.TELEGRAM_LINKED: {
        "telegram_username": "aliya",
        "telegram_user_id": 7,
    },
    NotificationType.OTP_RESET_REQUESTED: {
        "effective_at": "2026-10-09T09:00:00+00:00",
        "request_id": "r",
    },
    NotificationType.LOGIN_FAILURES: {"count": 5, "ip": "10.0.0.1"},
    NotificationType.ACCOUNT_CLOSING: {"closes_on": "2026-11-01"},
    NotificationType.MAIL_SUSPENDED: {"reason": "spam"},
    NotificationType.SYNC_ALERT: {"run_id": "r", "failed": 3, "total": 120},
    NotificationType.STUDENT_SYNC_FAILED: {"attempts": 6, "student_id": "s"},
    NotificationType.KNOWLEDGE_GAP: {
        "query": "dress code",
        "chat_kind": "student_chat",
        "chat_id": None,
        "notebook_id": None,
        "user_role": "student",
    },
    NotificationType.NOTEBOOK_ARTIFACT_READY: {
        "notebook_id": NOTEBOOK_ID,
        "artifact_id": ARTIFACT_ID,
        "kind": "mind_map",
        "title": "Photosynthesis",
    },
    NotificationType.ASSESSMENT_REMINDER: {
        "assessment_id": ASSESSMENT_ID,
        "subject_name": "Mathematics",
        "kind": "midterm",
        "control": "midterm_1",
        "title": "Algebra",
        "date": "2026-10-21",
        "period_end": None,
        "days_left": 3,
        "starts_at": "2026-10-21T04:00:00+00:00",
        "room": "204",
    },
    NotificationType.LIBRARY_ITEM_APPROVED: {"item_id": ITEM_ID, "title": "Algebra"},
    NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED: {
        "item_id": ITEM_ID,
        "title": "Algebra",
        "message": "Scan the pages straight.",
    },
    NotificationType.LIBRARY_ITEM_REJECTED: {
        "item_id": ITEM_ID,
        "title": "Algebra",
        "reason": "duplicate",
        "message": "It is already in the library.",
    },
    NotificationType.LIBRARY_ITEM_UNPUBLISHED: {
        "item_id": ITEM_ID,
        "title": "Algebra",
        "reason": "copyright",
        "note": "The publisher asked us.",
    },
    NotificationType.LIBRARY_QUEUE_WAITING: {"count": 7, "oldest_hours": 52},
    NotificationType.LIBRARY_REPORT_FILED: {
        "item_id": ITEM_ID,
        "title": "Algebra",
        "reason": "exam_leak",
    },
    NotificationType.LIBRARY_READING_LIST_NEW: {
        "list_id": LIST_ID,
        "title": "Start of term",
        "subject": "Physics",
    },
    NotificationType.LIBRARY_SUGGESTION_APPROVED: {
        "suggestion_id": ITEM_ID,
        "item_id": ITEM_ID,
        "title": "Algebra",
    },
    NotificationType.LIBRARY_SUGGESTION_DECLINED: {
        "suggestion_id": ITEM_ID,
        "title": "Algebra",
        "reason": "We already have it.",
    },
    NotificationType.CURATOR_EXAM_MARK: {
        "student_name": "Karimov Ali",
        "group_name": "2TN2",
        "subject_name": "Physics",
        "type": "midterm",
        "value": 3,
        "date": "2026-10-06",
    },
    NotificationType.LESSON_ABSENCE: {
        "lesson_id": LESSON_ID,
        "date": "2026-10-06",
        "period": 3,
        "subject_name": "Physics",
        "teacher_name": "Rustamov Aziz",
        "work_off_text": None,
        "due_date": None,
        "update": False,
    },
    NotificationType.CURATOR_ABSENCES: {
        "date": "2026-10-06",
        "group_id": "g",
        "group_name": "2TN2",
        "items": [
            {
                "student_id": "s1",
                "student_name": "Karimov Ali",
                "lesson_id": LESSON_ID,
                "period": 3,
                "subject_name": "Physics",
                "teacher_name": "Rustamov Aziz",
                "excused": False,
                "work_off_text": None,
            }
        ],
    },
    NotificationType.TEACHER_TEMPORARY_MARKS: {
        "date": "2026-10-20",
        "count": 1,
        "items": [
            {
                "lesson_id": LESSON_ID,
                "lesson_date": "2026-10-19",
                "period": 2,
                "group_name": "2TN2",
                "subject_name": "Physics",
                "student_id": "s1",
                "student_name": "Karimov Ali",
                "value": 4,
                "comment": None,
            }
        ],
    },
    NotificationType.FEEDBACK_NEW: {
        "feedback_id": "f",
        "kind": "bug",
        "area": "my",
        "title": "Marks page is blank",
        "reporter_name": "Karimov Ali",
    },
    NotificationType.FEEDBACK_RESPONSE: {
        "feedback_id": "f",
        "response_id": "r",
        "title": "Marks page is blank",
        "text": "Fixed, thank you!",
        "attachments": [],
    },
}


def test_the_sample_payloads_cover_every_notification_type() -> None:
    """WEB-27: every type has a description."""
    assert set(PAYLOADS) == set(NotificationType)


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
@pytest.mark.parametrize("notification_type", list(NotificationType))
def test_every_type_has_a_translated_title_and_body_in_every_language(
    i18n: I18nCore, notification_type: NotificationType, locale: str
) -> None:
    """WEB-27: no raw i18n key reaches the notification center."""
    result = describe(
        notification_type, PAYLOADS[notification_type], locale, i18n=i18n, urls=URLS
    )

    assert result.title
    assert "notify-" not in result.title + result.body


def test_marks_body_lists_marks_and_result_changes(i18n: I18nCore) -> None:
    """UF-BOT-04, BOT-11: subject, mark, type, date and semester mark changes."""
    result = describe(
        NotificationType.MARKS,
        PAYLOADS[NotificationType.MARKS],
        "en",
        i18n=i18n,
        urls=URLS,
    )

    assert result.title == "New marks"
    assert result.body.splitlines() == [
        "Mathematics — 5 (lesson), 06.10",
        "Physics — 3 (midterm), 06.10",
        "Semester mark: Physics 4.21 → 3.95",
    ]
    assert result.link == f"{URLS.sp}/grades/"


def test_broadcast_body_is_plain_text_of_the_html(i18n: I18nCore) -> None:
    """BOT-21: announcements appear in the center without markup."""
    result = describe(
        NotificationType.BROADCAST,
        PAYLOADS[NotificationType.BROADCAST],
        "en",
        i18n=i18n,
        urls=URLS,
    )

    assert result.title == "Exams"
    assert result.body == "Exams start\non Monday & Tuesday"
    assert result.link is None


def test_lesson_links_go_to_the_app_of_the_reader(i18n: I18nCore) -> None:
    """UF-BOT-07: students open the lesson in IHSP Web, teachers in the staff portal."""
    payload = PAYLOADS[NotificationType.LESSON_RESOURCES]

    student = describe(
        NotificationType.LESSON_RESOURCES, payload, "en", i18n=i18n, urls=URLS
    )
    teacher = describe(
        NotificationType.LESSON_RESOURCES,
        payload,
        "en",
        i18n=i18n,
        urls=URLS,
        staff=True,
    )

    assert student.link == f"{URLS.sp}/lessons/view/?id={LESSON_ID}"
    assert teacher.link == f"{URLS.staff}/lessons/view/?id={LESSON_ID}"
    assert student.body == "2TN2 · Physics · Period 3 · Room 102"


def test_lesson_changes_show_old_and_new_values(i18n: I18nCore) -> None:
    """BOT-11: a changed lesson shows what changed."""
    result = describe(
        NotificationType.LESSON_CHANGED,
        PAYLOADS[NotificationType.LESSON_CHANGED],
        "en",
        i18n=i18n,
        urls=URLS,
    )

    assert result.body.splitlines() == [
        "Physics, 07.10, period 2",
        "Room: 102 → 204",
        "Teacher: — → Kalandarova G.",
    ]


def test_a_cancelled_lesson_shows_the_status_in_the_readers_language(
    i18n: I18nCore,
) -> None:
    """ADM-10: "scheduled → cancelled" is translated, not printed as an enum value."""
    payload = {
        **PAYLOADS[NotificationType.LESSON_CHANGED],
        "changes": {"status": ["scheduled", "cancelled"]},
    }

    english = describe(
        NotificationType.LESSON_CHANGED, payload, "en", i18n=i18n, urls=URLS
    )
    russian = describe(
        NotificationType.LESSON_CHANGED, payload, "ru", i18n=i18n, urls=URLS
    )

    assert english.body.splitlines()[-1] == "Status: Scheduled → Cancelled"
    assert russian.body.splitlines()[-1] == "Статус: По расписанию → Отменён"


def test_emis_reauth_links_to_the_id_security_page(i18n: I18nCore) -> None:
    """ID-12: the notification leads to the EMIS password page."""
    result = describe(NotificationType.EMIS_REAUTH, {}, "ru", i18n=i18n, urls=URLS)

    assert result.link == f"{URLS.id}/security/emis/"


@pytest.mark.parametrize(
    ("locale", "title", "body"),
    [
        ("en", "Notebook output is ready", "Ready: Mind map “Photosynthesis”"),
        ("ru", "Материал блокнота готов", "Готово: Ментальная карта «Photosynthesis»"),
        ("uz", "Daftar materiali tayyor", "Tayyor: Aql xaritasi «Photosynthesis»"),
    ],
)
def test_a_ready_notebook_output_names_its_kind_and_title(
    i18n: I18nCore, locale: str, title: str, body: str
) -> None:
    """NB-21: the bell says which Studio output is ready, in the reader's language."""
    result = describe(
        NotificationType.NOTEBOOK_ARTIFACT_READY,
        PAYLOADS[NotificationType.NOTEBOOK_ARTIFACT_READY],
        locale,
        i18n=i18n,
        urls=URLS,
    )

    assert (result.title, result.body) == (title, body)


def test_a_ready_notebook_output_links_to_the_artifact_in_ihsp_web(
    i18n: I18nCore,
) -> None:
    """NB-21: the notification opens the notebook with the new output selected."""
    result = describe(
        NotificationType.NOTEBOOK_ARTIFACT_READY,
        PAYLOADS[NotificationType.NOTEBOOK_ARTIFACT_READY],
        "en",
        i18n=i18n,
        urls=URLS,
    )

    assert result.link == (
        f"{URLS.sp}/notebooks/view/?id={NOTEBOOK_ID}&artifact={ARTIFACT_ID}"
    )


@pytest.mark.parametrize(
    ("kind", "label"),
    [
        ("report", "Report"),
        ("mind_map", "Mind map"),
        ("flashcards", "Flash cards"),
        ("quiz", "Quiz"),
        ("data_table", "Data table"),
        ("slides", "Slide deck"),
        ("infographic", "Infographic"),
        ("podcast", "podcast"),
    ],
)
def test_every_studio_kind_has_a_label_and_an_unknown_one_is_shown_as_is(
    i18n: I18nCore, kind: str, label: str
) -> None:
    """NB-21: the kind label is translated; a kind added later never shows a key."""
    payload = {**PAYLOADS[NotificationType.NOTEBOOK_ARTIFACT_READY], "kind": kind}

    result = describe(
        NotificationType.NOTEBOOK_ARTIFACT_READY, payload, "en", i18n=i18n, urls=URLS
    )

    assert result.body == f"Ready: {label} “Photosynthesis”"


def test_lesson_absence_without_work_off_names_the_lesson(i18n: I18nCore) -> None:
    """A plain absence shows date, period, subject and teacher only."""
    result = describe(
        NotificationType.LESSON_ABSENCE,
        PAYLOADS[NotificationType.LESSON_ABSENCE],
        "en",
        i18n=i18n,
        urls=URLS,
    )

    assert result.body == "Physics (Rustamov Aziz), 06.10, period 3."
    assert result.link == f"{URLS.sp}/attendance/"


def test_lesson_absence_with_work_off_shows_text_and_due_date(i18n: I18nCore) -> None:
    """The work-off text and its due date follow the lesson line."""
    payload = {
        **PAYLOADS[NotificationType.LESSON_ABSENCE],
        "work_off_text": "Solve tasks 1-5",
        "due_date": "2026-10-13",
    }

    result = describe(
        NotificationType.LESSON_ABSENCE, payload, "en", i18n=i18n, urls=URLS
    )

    lines = result.body.split("\n")
    assert lines[1] == "Work-off task: Solve tasks 1-5"
    assert lines[2] == "Due by 13.10"


def test_lesson_absence_update_has_its_own_title(i18n: I18nCore) -> None:
    """A changed work-off task is announced as an update."""
    plain = PAYLOADS[NotificationType.LESSON_ABSENCE]
    update = {**plain, "update": True, "work_off_text": "Read chapter 4"}

    first = describe(NotificationType.LESSON_ABSENCE, plain, "en", i18n=i18n, urls=URLS)
    second = describe(
        NotificationType.LESSON_ABSENCE, update, "en", i18n=i18n, urls=URLS
    )

    assert second.title == "Work-off task updated"
    assert first.title != second.title


def test_curator_absences_list_one_line_per_item(i18n: I18nCore) -> None:
    """Group and date are in the title; items carry work-off and excused marks."""
    items = [
        {
            "student_name": "Karimov Ali",
            "period": 2,
            "subject_name": "Physics",
            "teacher_name": "Rustamov Aziz",
            "excused": False,
            "work_off_text": "Tasks 1-5",
        },
        {
            "student_name": "Karimov Ali",
            "period": 4,
            "subject_name": "Algebra",
            "teacher_name": "Ismoilova Dilya",
            "excused": True,
            "work_off_text": None,
        },
        {
            "student_name": "Umarov Timur",
            "period": 2,
            "subject_name": "Physics",
            "teacher_name": "Rustamov Aziz",
            "excused": False,
            "work_off_text": None,
        },
    ]
    payload = {**PAYLOADS[NotificationType.CURATOR_ABSENCES], "items": items}

    result = describe(
        NotificationType.CURATOR_ABSENCES, payload, "en", i18n=i18n, urls=URLS
    )

    assert result.title == "Absences in 2TN2, 06.10"
    assert result.body.split("\n") == [
        "Karimov Ali — period 2. Physics (Rustamov Aziz) · work-off: Tasks 1-5",
        "Karimov Ali — period 4. Algebra (Ismoilova Dilya) · excused",
        "Umarov Timur — period 2. Physics (Rustamov Aziz)",
    ]
    assert result.link == f"{URLS.staff}/group/attendance/"


def test_teacher_temporary_marks_list_one_line_per_item(i18n: I18nCore) -> None:
    """Count is in the title; one line per mark, a footer, a staff link."""
    item = PAYLOADS[NotificationType.TEACHER_TEMPORARY_MARKS]["items"][0]
    items = [
        item,
        {**item, "student_name": "Umarov Timur", "value": 3, "comment": "Quiz"},
    ]
    payload = {"date": "2026-10-20", "count": 2, "items": items}

    result = describe(
        NotificationType.TEACHER_TEMPORARY_MARKS,
        payload,
        "en",
        i18n=i18n,
        urls=URLS,
    )

    assert result.title == "Temporary marks to move to EMIS (2)"
    lines = result.body.split("\n")
    assert lines[0] == "19.10, period 2, 2TN2 · Physics: Karimov Ali — 4"
    assert (
        lines[1] == "19.10, period 2, 2TN2 · Physics: Umarov Timur — 3 · comment: Quiz"
    )
    assert len(lines) == 3
    assert result.link == f"{URLS.staff}/temporary-marks/"
