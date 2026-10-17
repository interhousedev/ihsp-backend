"""Contract modules import and their data types behave."""

import datetime as dt
import importlib
import logging
import re
from uuid import uuid4

from app.shared.actor import Role
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.identity import UserPreferences, UserRef, UserStatus
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.logging import configure_logging
from app.shared.notifications import NotificationType
from app.shared.wiring import ModuleDeps

import pytest
import structlog

CONTRACTS = [
    "identity",
    "emis",
    "academic",
    "files",
    "links",
    "ai",
    "flashcards",
    "mail",
    "lms",
    "notify",
    "auth",
    "callbacks",
]


@pytest.mark.parametrize("name", CONTRACTS)
def test_every_contract_module_imports(name: str) -> None:
    """§ 3.6: the files other agents import from exist."""
    assert importlib.import_module(f"app.shared.contracts.{name}")


def test_preferences_have_the_documented_defaults() -> None:
    """spec → Models → User → preferences."""
    prefs = UserPreferences()

    assert prefs.locale == "ru"
    assert prefs.marks_values == [2, 3, 4, 5]
    assert prefs.lessons_links_lead_min == 5
    assert prefs.today_cards[0] == "now"
    assert UserPreferences().onboarding_dismissed is not prefs.onboarding_dismissed


def test_a_lesson_ref_is_immutable() -> None:
    """Contract DTOs are frozen dataclasses."""
    now = dt.datetime(2026, 10, 6, 9, tzinfo=dt.UTC)
    lesson = LessonRef(
        id=uuid4(),
        date=now.date(),
        period=1,
        starts_at=now,
        ends_at=now,
        subject_id=uuid4(),
        subject_name="Math",
        teacher_id=None,
        room_id=None,
        room_slug=None,
        room_name=None,
        audience=("g",),
        group_names=("2TN2",),
        status="scheduled",
        topic=None,
        homework_text=None,
        homework_due_date=None,
    )

    with pytest.raises(AttributeError):
        lesson.period = 2  # type: ignore[misc]


def test_render_types_carry_the_message_and_its_recipient() -> None:
    """Renderers return RenderedMessage for a RenderContext."""
    user = UserRef(
        id=uuid4(),
        login="a.b",
        first_name="A",
        last_name="B",
        middle_name=None,
        roles=frozenset({Role.STUDENT}),
        status=UserStatus.ACTIVE,
        locale="ru",
        emis_status="active",
    )

    context = RenderContext(user=user, locale="ru", telegram_user_id=1)
    message = RenderedMessage(text_html="<b>hi</b>")

    assert context.user.status is UserStatus.ACTIVE
    assert message.buttons is None and message.documents == ()


def test_every_notification_type_is_unique() -> None:
    """Values are unique snake_case strings; the library adds 7 of the 29."""
    values = [t.value for t in NotificationType]

    assert len(values) == len(set(values)) == 29
    assert all(re.fullmatch("[a-z]+(_[a-z]+)*", value) for value in values)


def test_module_deps_is_frozen() -> None:
    """Modules receive one immutable bundle of infrastructure."""
    assert ModuleDeps.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert "settings" in ModuleDeps.__slots__


def test_configure_logging_routes_stdlib_records_through_structlog(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Structured JSON logs on stdout, also for stdlib loggers."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("INFO", json_logs=True)

        structlog.get_logger("test").info("hello", user_id="u1")
        logging.getLogger("uvicorn.error").info("from uvicorn")
        out = capsys.readouterr().out
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        structlog.reset_defaults()

    assert '"event": "hello"' in out and '"user_id": "u1"' in out
    assert "from uvicorn" in out


def test_bottom_nav_is_validated() -> None:
    """Up to 4 distinct whitelisted sp destinations, or None."""
    assert UserPreferences().bottom_nav is None
    assert UserPreferences(bottom_nav=["today", "grades"]).bottom_nav == [
        "today",
        "grades",
    ]
    assert UserPreferences(bottom_nav=["dashboard", "today"]).bottom_nav == [
        "dashboard",
        "today",
    ]
    for bad in (
        ["nope"],
        ["today"] * 2,
        ["today", "timetable", "subjects", "grades", "exams"],
    ):
        with pytest.raises(ValueError):
            UserPreferences(bottom_nav=bad)
