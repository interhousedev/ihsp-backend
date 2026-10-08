"""ADM-4, ADM-5, GEN-5, GEN-6: Administration routes under /v1/admin."""

from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from tests.fakes.identity.hydra import client
from tests.identity.http.conftest import Api

ADMIN_USER_FIELDS = {
    "id",
    "login",
    "first_name",
    "last_name",
    "middle_name",
    "roles",
    "status",
    "emis_status",
    "recovery_email",
    "mail_suspended",
    "created_at",
    "last_login_at",
}


async def test_admin_routes_need_the_admin_role(api: Api) -> None:
    """Contract: admin -> 401 without a token, 403 for others."""
    anonymous = await api.client.get("/v1/admin/users")
    student = await api.world.add_user()
    api.login_as(student)
    forbidden = await api.client.get("/v1/admin/users")
    teachers = await api.client.get("/v1/admin/teachers")
    audit = await api.client.get("/v1/admin/audit")
    clients = await api.client.get("/v1/admin/oauth-clients")

    assert anonymous.status_code == 401
    assert {
        forbidden.status_code,
        teachers.status_code,
        audit.status_code,
        clients.status_code,
    } == {403}
    assert forbidden.json()["type"] == "common/forbidden"


async def test_users_list_and_detail(api: Api) -> None:
    """UF-ADM-11: Page<AdminUser> and AdminUserDetail."""
    await api.admin()
    student = await api.world.add_user(login="s.tudent", recovery_email="s@example.org")
    api.world.add_session(student)
    api.world.add_link(student, 555, username="stud")

    listed = await api.client.get(
        "/v1/admin/users", params={"query": "s.tud", "role": "student"}
    )
    detail = await api.client.get(f"/v1/admin/users/{student.id}")

    assert listed.status_code == 200
    assert [u["login"] for u in listed.json()["items"]] == ["s.tudent"]
    assert set(listed.json()["items"][0]) == ADMIN_USER_FIELDS
    body = detail.json()
    assert set(body) == ADMIN_USER_FIELDS | {"telegram", "sessions", "recent_audit"}
    assert len(body["sessions"]) == 1 and body["telegram"][0]["username"] == "stud"


async def test_unknown_user_is_404_id_user_not_found(api: Api) -> None:
    """id/user-not-found."""
    from app.shared.ids import new_id

    await api.admin()

    response = await api.client.get(f"/v1/admin/users/{new_id()}")

    assert response.status_code == 404
    assert response.json()["type"] == "id/user-not-found"


async def test_block_unblock_roles_and_sessions_routes(api: Api) -> None:
    """ADM-5: the user management actions."""
    await api.admin()
    user = await api.world.add_user()
    session = api.world.add_session(user)

    blocked = await api.client.post(
        f"/v1/admin/users/{user.id}/block", json={"reason": "spam"}
    )
    unblocked = await api.client.post(f"/v1/admin/users/{user.id}/unblock")
    roles = await api.client.post(
        f"/v1/admin/users/{user.id}/roles", json={"grant": ["lms_admin"], "revoke": []}
    )
    revoked = await api.client.post(f"/v1/admin/users/{user.id}/sessions/revoke")

    assert blocked.json()["status"] == UserStatus.BLOCKED.value
    assert unblocked.json()["status"] == "active"
    assert sorted(roles.json()["roles"]) == ["lms_admin", "student"]
    assert revoked.status_code == 204
    assert api.world.store.sessions[session.id].revoked_at is not None


async def test_blocking_yourself_is_403(api: Api) -> None:
    """A safeguard: id/self-action-forbidden."""
    admin = await api.admin()

    response = await api.client.post(
        f"/v1/admin/users/{admin.user_id}/block", json={"reason": "x"}
    )

    assert response.status_code == 403
    assert response.json()["type"] == "id/self-action-forbidden"


async def test_reset_password_and_otp_routes(api: Api) -> None:
    """ADM-5: {activation_url} and 204."""
    await api.admin()
    other = await api.world.add_user(
        roles={Role.ADMIN},
        otp_enabled=True,
        login="o.a",
        recovery_email="oa@example.org",
    )
    api.world.add_link(other, 777)

    reset = await api.client.post(f"/v1/admin/users/{other.id}/reset-password")
    otp = await api.client.post(f"/v1/admin/users/{other.id}/reset-otp")

    assert reset.json()["activation_url"].startswith(
        "http://localhost:3001/activate/?token="
    )
    assert otp.status_code == 204
    assert api.world.store.links == {}


async def test_resetting_your_own_admin_account_is_403(api: Api) -> None:
    """ID-23: id/admin-reset-forbidden."""
    admin = await api.admin()

    response = await api.client.post(f"/v1/admin/users/{admin.user_id}/reset-password")

    assert response.status_code == 403
    assert response.json()["type"] == "id/admin-reset-forbidden"


async def test_mail_suspend_and_resume_routes(api: Api) -> None:
    """MAIL-8: AdminUser.mail_suspended."""
    await api.admin()
    user = await api.world.add_user()

    suspended = await api.client.post(
        f"/v1/admin/users/{user.id}/mail/suspend", json={"reason": "spam"}
    )
    resumed = await api.client.post(f"/v1/admin/users/{user.id}/mail/resume")

    assert suspended.json()["mail_suspended"] is True
    assert resumed.json()["mail_suspended"] is False


async def test_teacher_routes(api: Api) -> None:
    """ADM-4: create (201 with the link), list, patch, deactivate."""
    await api.admin()

    created = await api.client.post(
        "/v1/admin/teachers",
        json={
            "last_name": "Kalandarova",
            "first_name": "Gavxar",
            "middle_name": "X",
            "email": "t@example.org",
        },
    )
    teacher_id = created.json()["user"]["id"]
    listed = await api.client.get(
        "/v1/admin/teachers", params={"status": "pending_activation"}
    )
    patched = await api.client.patch(
        f"/v1/admin/teachers/{teacher_id}", json={"last_name": "Kalandarova-Aliyeva"}
    )
    deactivated = await api.client.post(f"/v1/admin/teachers/{teacher_id}/deactivate")

    assert created.status_code == 201
    assert created.json()["user"]["login"] == "kalandarova.gavxar"
    assert created.json()["user"]["status"] == "pending_activation"
    assert [t["id"] for t in listed.json()["items"]] == [teacher_id]
    assert patched.json()["last_name"] == "Kalandarova-Aliyeva"
    assert deactivated.json()["status"] == "deactivated"
    assert api.world.kicker.names() == ["academic.teacher_deactivated"]


async def test_duplicate_teacher_email_is_409(api: Api) -> None:
    """id/email-taken."""
    await api.admin()
    body = {"last_name": "A", "first_name": "B", "email": "t@example.org"}
    await api.client.post("/v1/admin/teachers", json=body)

    response = await api.client.post(
        "/v1/admin/teachers", json={**body, "first_name": "C"}
    )

    assert response.status_code == 409
    assert response.json()["type"] == "id/email-taken"


async def test_audit_route_filters_and_names_actors(api: Api) -> None:
    """UF-ADM-13: Page<AuditItem> with actor PersonRef."""
    admin = await api.admin()
    user = await api.world.add_user()
    await api.client.post(f"/v1/admin/users/{user.id}/block", json={"reason": "x"})

    response = await api.client.get(
        "/v1/admin/audit", params={"user_id": str(user.id), "type": "user.blocked"}
    )

    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert item["type"] == "user.blocked" and item["metadata"] == {"reason": "x"}
    assert item["actor"] == {
        "id": str(admin.user_id),
        "first_name": "Aleksey",
        "last_name": "Brastilov",
    }


async def test_oauth_client_routes(api: Api) -> None:
    """MCP-3: list and verify."""
    await api.admin()
    api.world.hydra.clients["claude"] = client("claude")

    listed = await api.client.get("/v1/admin/oauth-clients")
    verified = await api.client.post(
        "/v1/admin/oauth-clients/claude/verify", json={"verified": True}
    )
    missing = await api.client.post(
        "/v1/admin/oauth-clients/nope/verify", json={"verified": True}
    )

    assert listed.json() == [
        {
            "client_id": "claude",
            "name": "Client claude",
            "verified": False,
            "dynamic": True,
            "last_used_at": None,
        }
    ]
    assert verified.json()["verified"] is True
    assert missing.status_code == 404
