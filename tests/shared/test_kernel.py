"""Errors, actor, clock, container."""

from datetime import UTC, datetime

from app.bootstrap.container import build_infrastructure
from app.settings import Settings
from app.shared.actor import SYSTEM_ACTOR, Actor, Role
from app.shared.base_error import (
    BaseError,
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    ValidationFailedError,
)
from app.shared.clock import SystemClock, local_today, to_local
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.parametrize(
    ("error", "code", "status"),
    [
        (BaseError, "common/internal", 500),
        (NotFoundError, "common/not-found", 404),
        (ForbiddenError, "common/forbidden", 403),
        (UnauthorizedError, "auth/unauthorized", 401),
        (ConflictError, "common/conflict", 409),
        (ValidationFailedError, "common/validation", 422),
        (RateLimitedError, "common/rate-limited", 429),
        (GoneError, "common/gone", 410),
    ],
)
def test_kernel_errors_have_stable_codes_and_statuses(
    error: type[BaseError], code: str, status: int
) -> None:
    """GEN-8: stable code (the problem+json type) and HTTP status."""
    raised = error(params={"a": 1})

    assert (raised.code, raised.status) == (code, status)
    assert raised.params == {"a": 1}
    assert raised.support_details == code
    assert raised.notify_user is True


def test_a_module_error_subclasses_a_kernel_error() -> None:
    """Modules add their own code and message key."""

    class AttendanceWindowClosedError(ForbiddenError):
        """Edit window is over."""

        code = "attendance/window-closed"
        message_key = "attendance-window-closed"

    raised = AttendanceWindowClosedError(support_details="8 days")

    assert (raised.code, raised.status) == ("attendance/window-closed", 403)
    assert str(raised) == "8 days"


def test_require_passes_for_a_held_role_and_forbids_otherwise() -> None:
    """Actor.require raises ForbiddenError listing the roles."""
    teacher = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))

    teacher.require(Role.ADMIN, Role.TEACHER)
    with pytest.raises(ForbiddenError) as caught:
        teacher.require(Role.ADMIN)

    assert teacher.has(Role.TEACHER) and not teacher.has(Role.ADMIN)
    assert caught.value.params == {"roles": ["admin"]}


def test_the_system_actor_holds_every_role() -> None:
    """Jobs run as the system actor."""
    assert SYSTEM_ACTOR.roles == frozenset(Role)
    assert int(SYSTEM_ACTOR.user_id) == 0


def test_local_today_uses_tashkent_time() -> None:
    """Tashkent is UTC+5: 22:00 UTC is already the next day."""
    clock = FixedClock(datetime(2026, 10, 6, 22, 0, tzinfo=UTC))

    assert local_today(clock).isoformat() == "2026-10-07"
    assert to_local(clock.now()).hour == 3


def test_system_clock_is_timezone_aware_utc() -> None:
    """Never naive datetimes."""
    offset = SystemClock().now().utcoffset()

    assert offset is not None and offset.total_seconds() == 0


def test_fixed_clock_advances() -> None:
    """The test clock only moves on advance()."""
    clock = FixedClock()

    clock.advance(hours=24)

    assert clock.now() == datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


async def test_the_container_holds_infrastructure_and_empty_module_slots(
    settings: Settings,
) -> None:
    """§ 3.12: infrastructure fields set, module fields None until I1 wires them."""
    container = build_infrastructure(settings, FakeTaskKicker())

    try:
        assert isinstance(container.engine, AsyncEngine)
        assert container.identity is None and container.lms is None
        assert container.i18n.t("en", "common-yes") == "Yes"
    finally:
        await container.close()
