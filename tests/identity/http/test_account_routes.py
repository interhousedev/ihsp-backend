"""ID-17 to ID-27: the /v1/id/me routes."""

from tests.identity.http.conftest import Api
from tests.identity.support import PASSWORD

ME = "/v1/id/me"


async def test_account_routes_need_a_bearer_token(api: Api) -> None:
    """Contract: bearer auth -> 401 problem+json without one."""
    for method, path in (
        ("GET", ME),
        ("PATCH", f"{ME}/preferences"),
        ("GET", f"{ME}/sessions"),
        ("GET", f"{ME}/telegram"),
        ("GET", f"{ME}/connectors"),
        ("GET", f"{ME}/activity"),
    ):
        response = await api.client.request(
            method, path, json={} if method == "PATCH" else None
        )
        assert response.status_code == 401, (method, path)
        assert response.json()["type"] == "auth/unauthorized"


async def test_get_me_returns_the_user_me_shape(api: Api) -> None:
    """Schemas: UserMe."""
    user = await api.world.add_user(preferences={"locale": "uz"})
    api.world.add_link(user, 555, username="ali")
    api.login_as(user)

    response = await api.client.get(ME)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "login",
        "first_name",
        "last_name",
        "middle_name",
        "roles",
        "status",
        "recovery_email",
        "otp_enabled",
        "otp_via_email",
        "emis_status",
        "mailbox",
        "preferences",
        "telegram",
    }
    assert body["roles"] == ["student"] and body["status"] == "active"
    assert body["mailbox"] == f"{user.login}@mail.ihsu.uz"
    assert body["preferences"]["locale"] == "uz"
    assert body["preferences"]["marks_values"] == [2, 3, 4, 5]
    assert body["telegram"] == [
        {
            "telegram_user_id": 555,
            "username": "ali",
            "otp_delivery": True,
            "blocked": False,
            "linked_at": api.world.clock.now().isoformat().replace("+00:00", "Z"),
        }
    ]


async def test_theme_defaults_to_light_until_the_user_chooses(api: Api) -> None:
    """WEB-17: a new account paints light; the saved choice wins on every platform."""
    user = await api.world.add_user(preferences={"locale": "uz"})
    api.login_as(user)

    fresh = await api.client.get(ME)
    await api.client.patch(f"{ME}/preferences", json={"theme": "system"})
    chosen = await api.client.get(ME)

    assert fresh.json()["preferences"]["theme"] == "light"
    assert chosen.json()["preferences"]["theme"] == "system"


async def test_patch_preferences_merges_and_returns_the_document(api: Api) -> None:
    """WEB-17: partial UserPreferences in, the full document out."""
    user = await api.world.add_user()
    api.login_as(user)

    response = await api.client.patch(
        f"{ME}/preferences", json={"theme": "dark", "alerts_gpa_below": 4.2}
    )

    assert response.status_code == 200
    assert (
        response.json()["theme"] == "dark"
        and response.json()["alerts_gpa_below"] == 4.2
    )
    cleared = await api.client.patch(
        f"{ME}/preferences", json={"alerts_gpa_below": None}
    )
    assert cleared.json()["alerts_gpa_below"] is None
    assert cleared.json()["theme"] == "dark"


async def test_patch_preferences_rejects_unknown_and_invalid_values(api: Api) -> None:
    """Validation errors are 422."""
    user = await api.world.add_user()
    api.login_as(user)

    unknown = await api.client.patch(f"{ME}/preferences", json={"nope": 1})
    invalid = await api.client.patch(f"{ME}/preferences", json={"theme": "neon"})

    assert unknown.status_code == invalid.status_code == 422


async def test_password_change_is_204(api: Api) -> None:
    """Contract: POST /v1/id/me/password -> 204."""
    user = await api.world.add_user()
    api.login_as(user)

    response = await api.client.post(
        f"{ME}/password",
        json={"current_password": PASSWORD, "new_password": "N3wStrongPass"},
    )

    assert response.status_code == 204 and response.content == b""


async def test_sessions_list_and_revoke_routes(api: Api) -> None:
    """UF-ID-11: SessionItem[], DELETE 204, revoke-others 204."""
    user = await api.world.add_user()
    current = api.world.add_session(user)
    other = api.world.add_session(user)
    third = api.world.add_session(user)
    api.login_as(user, session=current)

    listed = await api.client.get(f"{ME}/sessions")
    deleted = await api.client.delete(f"{ME}/sessions/{other.id}")
    others = await api.client.post(f"{ME}/sessions/revoke-others")

    assert listed.status_code == 200
    items = {item["id"]: item for item in listed.json()}
    assert items[str(current.id)]["current"] is True
    assert set(items[str(current.id)]) == {
        "id",
        "ip",
        "user_agent",
        "amr",
        "last_seen_at",
        "current",
    }
    assert deleted.status_code == 204
    assert others.status_code == 204
    assert api.world.store.sessions[third.id].revoked_at is not None
    assert api.world.store.sessions[current.id].revoked_at is None
    missing = await api.client.delete(f"{ME}/sessions/{other.id}")
    assert missing.status_code == 404


async def test_telegram_routes(api: Api) -> None:
    """ID-21: list, PATCH otp_delivery, DELETE."""
    user = await api.world.add_user()
    api.world.add_link(user, 555)
    api.login_as(user)

    listed = await api.client.get(f"{ME}/telegram")
    patched = await api.client.patch(f"{ME}/telegram/555", json={"otp_delivery": False})
    deleted = await api.client.delete(f"{ME}/telegram/555")
    again = await api.client.delete(f"{ME}/telegram/555")

    assert [a["telegram_user_id"] for a in listed.json()] == [555]
    assert patched.json()["otp_delivery"] is False
    assert deleted.status_code == 204
    assert again.status_code == 404


async def test_otp_enable_confirm_and_disable_routes(api: Api) -> None:
    """UF-ID-06: enable 202, confirm -> UserMe, disable -> UserMe."""
    user = await api.world.add_user()
    api.login_as(user)

    enabled = await api.client.post(f"{ME}/otp/enable", json={"via_email": True})
    confirmed = await api.client.post(
        f"{ME}/otp/enable/confirm", json={"code": api.world.otp.last("otp-enable").code}
    )
    disabled = await api.client.post(f"{ME}/otp/disable", json={"password": PASSWORD})

    assert enabled.status_code == 202
    assert (
        confirmed.json()["otp_enabled"] is True
        and confirmed.json()["otp_via_email"] is True
    )
    assert disabled.json()["otp_enabled"] is False


async def test_otp_enable_without_a_channel_is_422(api: Api) -> None:
    """id/otp-no-channel."""
    user = await api.world.add_user()
    api.login_as(user)

    response = await api.client.post(f"{ME}/otp/enable", json={"via_email": False})

    assert response.status_code == 422
    assert response.json()["type"] == "id/otp-no-channel"


async def test_email_change_routes(api: Api) -> None:
    """ID-25: 202 then UserMe with the new email."""
    user = await api.world.add_user()
    api.login_as(user)

    started = await api.client.post(
        f"{ME}/email/change",
        json={"password": PASSWORD, "new_email": "new@example.org"},
    )
    confirmed = await api.client.post(
        f"{ME}/email/change/confirm",
        json={"code": api.world.email.last_code("new@example.org")},
    )

    assert started.status_code == 202
    assert confirmed.json()["recovery_email"] == "new@example.org"


async def test_activity_route_paginates(api: Api) -> None:
    """UF-ID-14: Page<AuditItem>."""
    user = await api.world.add_user()
    api.login_as(user)
    for _ in range(3):
        api.world.clock.advance(minutes=1)
        await api.client.post(f"{ME}/otp/enable", json={"via_email": True})
        await api.world.redis.flushall()
        await api.client.post(
            f"{ME}/password",
            json={"current_password": PASSWORD, "new_password": "N3wStrongPass"},
        )
        await api.client.post(
            f"{ME}/password",
            json={"current_password": "N3wStrongPass", "new_password": PASSWORD},
        )

    first = await api.client.get(f"{ME}/activity", params={"limit": 2})
    second = await api.client.get(
        f"{ME}/activity", params={"limit": 2, "cursor": first.json()["next_cursor"]}
    )

    assert first.status_code == 200
    assert len(first.json()["items"]) == 2 and first.json()["next_cursor"]
    item = first.json()["items"][0]
    assert set(item) == {
        "id",
        "type",
        "ip",
        "user_agent",
        "actor",
        "created_at",
        "metadata",
    }
    assert item["type"] == "password.changed" and item["actor"] is None
    assert len(second.json()["items"]) == 2


async def test_step_up_is_202(api: Api) -> None:
    """Contract addition: POST /v1/id/me/step-up."""
    user = await api.world.add_user()
    api.login_as(user)

    response = await api.client.post(f"{ME}/step-up")

    assert response.status_code == 202
    assert api.world.otp.last("step-up").user_id == user.id


async def test_connector_routes(api: Api) -> None:
    """MCP-2, MCP-4: create (201 with the token), list, revoke (204)."""
    user = await api.world.add_user()
    api.login_as(user)
    body = {
        "server": "student",
        "name": "Claude",
        "scopes": ["schedule:read"],
        "expires_in_days": 30,
    }

    created = await api.client.post(f"{ME}/connectors", json=body)
    token = created.json()["token"]
    connector = created.json()["connector"]
    listed = await api.client.get(f"{ME}/connectors")
    revoked = await api.client.delete(f"{ME}/connectors/{connector['id']}")
    relisted = await api.client.get(f"{ME}/connectors")

    assert created.status_code == 201
    assert token.startswith("ihsp_mcp_")
    assert set(connector) == {
        "id",
        "name",
        "server",
        "scopes",
        "course_ids",
        "kind",
        "token_prefix",
        "created_at",
        "last_used_at",
        "expires_at",
        "revoked_at",
    }
    assert connector["kind"] == "token" and connector["revoked_at"] is None
    assert token not in listed.text and token[len("ihsp_mcp_") :] not in listed.text
    assert listed.json()[0]["token_prefix"] == token[len("ihsp_mcp_") :][:8]
    assert revoked.status_code == 204
    assert relisted.json()[0]["revoked_at"] is not None


async def test_invalid_connector_is_422(api: Api) -> None:
    """id/connector-invalid."""
    user = await api.world.add_user()
    api.login_as(user)

    response = await api.client.post(
        f"{ME}/connectors",
        json={
            "server": "student",
            "name": "x",
            "scopes": ["bogus"],
            "expires_in_days": 30,
        },
    )

    assert response.status_code == 422
    assert response.json()["type"] == "id/connector-invalid"
