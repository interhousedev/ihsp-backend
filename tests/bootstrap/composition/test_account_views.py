"""AccountViews over a fake `GetUserDetail`: the `AdminUserDetail` shape."""

import datetime as dt

from app.bootstrap.adapters.composition.account_views import AccountViewsAdapter
from app.interfaces.http.v1.composition.shared_schemas import (
    AdminUserResponse,
    AuditItemResponse,
    SessionItemResponse,
    TelegramAccountResponse,
)
from app.modules.identity.application.get_user_detail import UserDetail
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import AuditEventRecord
from app.modules.identity.domain.session import LoginSession
from app.modules.identity.domain.telegram_link import TelegramLink
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.bootstrap.composition.data import NOW
from tests.bootstrap.composition.fakes import FakeUseCase
from tests.factories import make_actor
from tests.identity.support import make_user


async def test_account_is_the_admin_user_detail_as_json() -> None:
    """User fields, Telegram, sessions and audit with the actor named."""
    admin = make_user(first_name="Dilshod", last_name="Rakhimov", roles={Role.ADMIN})
    student = make_user(first_name="Aziza", last_name="Karimova")
    link = TelegramLink(
        telegram_user_id=777,
        user_id=student.id,
        first_name="Aziza",
        username="aziza",
        linked_at=NOW,
    )
    session = LoginSession(
        id=new_id(),
        user_id=student.id,
        ip="10.0.0.5",
        user_agent="Firefox",
        expires_at=NOW + dt.timedelta(days=30),
        last_seen_at=NOW,
        amr=["pwd"],
    )
    event = AuditEventRecord(
        id=new_id(),
        type="student.viewed",
        created_at=NOW,
        user_id=student.id,
        actor_id=admin.id,
        ip="10.0.0.9",
        user_agent="Chrome",
        metadata={"reason": "support"},
    )
    detail = UserDetail(
        user=student,
        telegram=[link],
        sessions=[session],
        recent_audit=[event],
        actors={admin.id: admin},
    )
    get_user_detail = FakeUseCase(detail)
    views = AccountViewsAdapter(get_user_detail)  # type: ignore[arg-type]
    actor = make_actor(Role.ADMIN, user_id=admin.id)

    account = await views.account(
        actor, student.id, ip="203.0.113.7", user_agent="Safari"
    )

    assert get_user_detail.calls == [
        (
            (actor, student.id, RequestContext(ip="203.0.113.7", user_agent="Safari")),
            {},
        )
    ]
    user = AdminUserResponse.model_validate(account)
    assert str(user.id) == str(student.id) and user.roles == ["student"]
    assert account["login"] == student.login
    assert [
        TelegramAccountResponse.model_validate(t).username for t in account["telegram"]
    ] == ["aziza"]
    assert SessionItemResponse.model_validate(account["sessions"][0]).amr == ["pwd"]
    audit = AuditItemResponse.model_validate(account["recent_audit"][0])
    assert audit.type == "student.viewed"
    assert audit.actor is not None and audit.actor.last_name == "Rakhimov"
    assert audit.metadata == {"reason": "support"}
    assert dt.datetime.fromisoformat(account["created_at"]) == student.created_at
