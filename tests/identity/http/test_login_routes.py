"""ID-12 to ID-16, ID-19, ID-23 to ID-27: the login app routes under /v1/id."""

from datetime import timedelta

from app.shared.actor import Role
from tests.fakes.identity.hydra import client
from tests.identity.http.conftest import Api
from tests.identity.support import PASSWORD, sign_init_data

from httpx import Response


def error_type(response: Response) -> str:
    """The problem+json type."""
    assert response.headers["content-type"] == "application/problem+json"
    return response.json()["type"]


# - - - Login - - -


async def test_get_login_describes_the_request(api: Api) -> None:
    """GET /v1/id/login -> LoginInfo."""
    api.world.hydra.add_login("lc-1", client_id="admin")

    response = await api.client.get("/v1/id/login", params={"login_challenge": "lc-1"})

    assert response.status_code == 200
    assert response.json() == {
        "client_id": "admin",
        "client_name": "Client admin",
        "skip": False,
        "requires_second_factor": True,
        "redirect_to": None,
    }


async def test_get_login_without_a_challenge_is_a_validation_error(api: Api) -> None:
    """The challenge is required."""
    response = await api.client.get("/v1/id/login")

    assert response.status_code == 422
    assert error_type(response) == "common/request-validation"


async def test_post_login_returns_the_redirect(api: Api) -> None:
    """POST /v1/id/login -> LoginResult."""
    user = await api.world.add_user()
    api.world.hydra.add_login("lc-1")

    response = await api.client.post(
        "/v1/id/login",
        json={"login_challenge": "lc-1", "login": user.login, "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json() == {
        "redirect_to": "https://hydra/continue?login_verifier=lc-1",
        "second_factor": None,
    }


async def test_post_login_with_a_wrong_password_is_401_problem_json(api: Api) -> None:
    """ID-15: generic error."""
    user = await api.world.add_user()
    api.world.hydra.add_login("lc-1")

    response = await api.client.post(
        "/v1/id/login",
        json={"login_challenge": "lc-1", "login": user.login, "password": "nope"},
    )

    assert response.status_code == 401
    assert error_type(response) == "auth/invalid-credentials"
    assert response.json()["message_key"] == "id-invalid-credentials"
    assert response.json()["title"] == "Wrong login or password."


async def test_post_login_for_administration_returns_a_second_factor(api: Api) -> None:
    """ID-11: ticket and channels."""
    admin = await api.world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    api.world.hydra.add_login("lc-1", client_id="admin")

    response = await api.client.post(
        "/v1/id/login",
        json={"login_challenge": "lc-1", "login": admin.login, "password": PASSWORD},
    )

    body = response.json()
    assert body["redirect_to"] is None
    assert body["second_factor"]["method"] == "otp"
    assert body["second_factor"]["channels"] == ["email"]
    ticket = body["second_factor"]["ticket"]

    done = await api.client.post(
        "/v1/id/login/otp",
        json={
            "login_challenge": "lc-1",
            "login": admin.login,
            "code": api.world.otp.last("login2fa").code,
            "ticket": ticket,
        },
    )
    assert done.status_code == 200
    assert done.json()["redirect_to"]


async def test_used_challenge_is_410_with_the_redirect_to_follow(api: Api) -> None:
    """auth/challenge-used carries params.redirect_to."""
    api.world.hydra.add_login("lc-1")
    api.world.hydra.used.add("lc-1")

    response = await api.client.get("/v1/id/login", params={"login_challenge": "lc-1"})

    assert response.status_code == 410
    assert error_type(response) == "auth/challenge-used"
    assert response.json()["params"]["redirect_to"] == "https://hydra/restart"


async def test_login_locks_with_423_and_retry_after(api: Api) -> None:
    """ID-15: auth/locked."""
    user = await api.world.add_user()
    api.world.hydra.add_login("lc-1")
    body = {"login_challenge": "lc-1", "login": user.login, "password": "nope"}
    for _ in range(5):
        await api.client.post("/v1/id/login", json=body)

    response = await api.client.post("/v1/id/login", json=body)

    assert response.status_code == 423
    assert error_type(response) == "auth/locked"
    assert response.json()["params"]["retry_after"] == 60


async def test_otp_request_is_always_202_sent_true(api: Api) -> None:
    """ID-13: the same answer for unknown logins."""
    response = await api.client.post(
        "/v1/id/login/otp/request",
        json={"login_challenge": "lc-1", "login": "nobody.here"},
    )

    assert response.status_code == 202
    assert response.json() == {"sent": True}


async def test_otp_request_accepts_an_empty_challenge(api: Api) -> None:
    """The mini app page has no Hydra challenge."""
    user = await api.world.add_user(otp_enabled=True, otp_via_email=True)

    response = await api.client.post(
        "/v1/id/login/otp/request", json={"login_challenge": "", "login": user.login}
    )

    assert response.status_code == 202
    assert api.world.otp.count("login") == 1


async def test_passwordless_otp_login(api: Api) -> None:
    """UF-ID-03."""
    user = await api.world.add_user(otp_enabled=True, otp_via_email=True)
    api.world.hydra.add_login("lc-1")
    await api.client.post(
        "/v1/id/login/otp/request",
        json={"login_challenge": "lc-1", "login": user.login},
    )

    response = await api.client.post(
        "/v1/id/login/otp",
        json={
            "login_challenge": "lc-1",
            "login": user.login,
            "code": api.world.otp.last().code,
        },
    )

    assert response.status_code == 200
    assert response.json()["redirect_to"]


async def test_wrong_otp_code_is_401_with_attempts_left(api: Api) -> None:
    """ID-14."""
    user = await api.world.add_user(otp_enabled=True, otp_via_email=True)
    api.world.hydra.add_login("lc-1")
    await api.client.post(
        "/v1/id/login/otp/request",
        json={"login_challenge": "lc-1", "login": user.login},
    )
    good = api.world.otp.last().code

    response = await api.client.post(
        "/v1/id/login/otp",
        json={
            "login_challenge": "lc-1",
            "login": user.login,
            "code": "000000" if good != "000000" else "111111",
        },
    )

    assert response.status_code == 401
    assert error_type(response) == "auth/otp-invalid"
    assert response.json()["params"] == {"attempts_left": 2}


# - - - Consent and logout - - -


async def test_consent_for_a_first_party_client_returns_the_redirect(api: Api) -> None:
    """GET /v1/id/consent -> ConsentInfo with redirect_to."""
    user = await api.world.add_user()
    session = api.world.add_session(user)
    api.world.hydra.add_consent(
        "cc-1",
        client_id="sp",
        subject=str(user.id),
        context={"session_id": str(session.id)},
    )

    response = await api.client.get(
        "/v1/id/consent", params={"consent_challenge": "cc-1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["redirect_to"] == "https://hydra/code?consent_verifier=cc-1"
    assert body["server"] is None and body["verified"] is True


async def test_consent_screen_data_and_approval_for_an_mcp_client(api: Api) -> None:
    """MCP-3: the screen data, then POST /v1/id/consent creates the connector."""
    user = await api.world.add_user()
    api.world.hydra.add_consent(
        "cc-1",
        client_id="claude",
        subject=str(user.id),
        request_url=(
            "https://hydra/oauth2/auth?resource=https://api/mcp/student"
            "&redirect_uri=https://claude.ai/cb"
        ),
        requested_scope=("openid", "schedule:read"),
        context={"session_id": "x"},
    )

    info = await api.client.get("/v1/id/consent", params={"consent_challenge": "cc-1"})
    done = await api.client.post(
        "/v1/id/consent",
        json={
            "consent_challenge": "cc-1",
            "accept": True,
            "grant_scopes": ["schedule:read"],
        },
    )

    assert info.json() | {"redirect_to": None} == {
        "client_id": "claude",
        "client_name": "Client claude",
        "verified": False,
        "redirect_domain": "claude.ai",
        "server": "student",
        "requested_scopes": ["schedule:read"],
        "requires_otp": False,
        "redirect_to": None,
    }
    assert done.status_code == 200
    assert done.json() == {"redirect_to": "https://hydra/code?consent_verifier=cc-1"}
    assert len(api.world.store.connectors) == 1


async def test_consent_otp_route_sends_the_step_up_code(api: Api) -> None:
    """Gap 2: POST /v1/id/consent/otp -> 202, then POST /v1/id/consent verifies it."""
    admin = await api.world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    api.world.hydra.clients["trusted"] = client("trusted", verified=True, dynamic=False)
    mfa_at = (api.world.clock.now() - timedelta(hours=1)).isoformat()
    api.world.hydra.add_consent(
        "cc-1",
        client_id="trusted",
        subject=str(admin.id),
        request_url="https://hydra/oauth2/auth?resource=https://api/mcp/admin",
        requested_scope=("openid", "people:read"),
        context={"session_id": "x", "amr": ["pwd", "otp"], "mfa_at": mfa_at},
    )

    sent = await api.client.post(
        "/v1/id/consent/otp", json={"consent_challenge": "cc-1"}
    )
    refused = await api.client.post(
        "/v1/id/consent",
        json={
            "consent_challenge": "cc-1",
            "accept": True,
            "grant_scopes": ["people:read"],
        },
    )
    accepted = await api.client.post(
        "/v1/id/consent",
        json={
            "consent_challenge": "cc-1",
            "accept": True,
            "grant_scopes": ["people:read"],
            "otp_code": api.world.otp.last("step-up").code,
        },
    )

    assert sent.status_code == 202
    assert refused.status_code == 401
    assert error_type(refused) == "auth/second-factor-required"
    assert accepted.status_code == 200
    assert api.world.hydra.last("accept_consent")["grant_audience"] == ["mcp-admin"]


async def test_consent_otp_for_a_first_party_challenge_is_refused(api: Api) -> None:
    """Only MCP consents send step-up codes."""
    user = await api.world.add_user()
    api.world.hydra.add_consent("cc-1", client_id="sp", subject=str(user.id))

    response = await api.client.post(
        "/v1/id/consent/otp", json={"consent_challenge": "cc-1"}
    )

    assert response.status_code == 404
    assert api.world.otp.codes == []


async def test_logout_challenge_returns_the_hydra_redirect(api: Api) -> None:
    """GET /v1/id/logout -> {redirect_to}."""
    from app.modules.identity.ports.hydra_gateway import LogoutRequest

    api.world.hydra.logout_requests["lo-1"] = LogoutRequest("lo-1", None, None)

    response = await api.client.get(
        "/v1/id/logout", params={"logout_challenge": "lo-1"}
    )

    assert response.status_code == 200
    assert response.json() == {"redirect_to": "https://hydra/after-logout"}


# - - - Telegram - - -


async def test_telegram_status_and_login_routes(api: Api) -> None:
    """UF-BOT-01: status, then login links the account."""
    user = await api.world.add_user()
    init_data = sign_init_data(auth_date=int(api.world.clock.now().timestamp()))

    before = await api.client.post(
        "/v1/id/telegram/status", json={"init_data": init_data}
    )
    linked = await api.client.post(
        "/v1/id/telegram/login",
        json={"init_data": init_data, "login": user.login, "password": PASSWORD},
    )
    after = await api.client.post(
        "/v1/id/telegram/status", json={"init_data": init_data}
    )

    assert before.json() == {"linked": False, "login": None}
    assert linked.status_code == 200
    assert linked.json() == {"linked": True, "login": user.login}
    assert after.json() == {"linked": True, "login": user.login}


async def test_telegram_login_second_factor_for_administration(api: Api) -> None:
    """Union response: {linked, login} | LoginResult."""
    admin = await api.world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    init_data = sign_init_data(auth_date=int(api.world.clock.now().timestamp()))
    body = {"init_data": init_data, "login": admin.login, "password": PASSWORD}

    first = await api.client.post("/v1/id/telegram/login", json=body)
    second = await api.client.post(
        "/v1/id/telegram/login",
        json={**body, "otp_code": api.world.otp.last("tg-login").code},
    )

    assert first.json()["second_factor"]["method"] == "otp"
    assert "linked" not in first.json()
    assert second.json() == {"linked": True, "login": admin.login}


async def test_telegram_account_linked_elsewhere_is_409(api: Api) -> None:
    """UF-BOT-01 5a: telegram/linked-elsewhere."""
    owner = await api.world.add_user()
    api.world.add_link(owner, 555)
    other = await api.world.add_user(login="o.t", recovery_email="o@example.org")
    init_data = sign_init_data(auth_date=int(api.world.clock.now().timestamp()))

    response = await api.client.post(
        "/v1/id/telegram/login",
        json={"init_data": init_data, "login": other.login, "password": PASSWORD},
    )

    assert response.status_code == 409
    assert error_type(response) == "telegram/linked-elsewhere"


async def test_telegram_otp_request_route_then_login_with_the_code(api: Api) -> None:
    """Gap 1: POST /v1/id/telegram/otp/request {init_data, login} -> 202 {sent}."""
    user = await api.world.add_user(otp_enabled=True, otp_via_email=True)
    init_data = sign_init_data(auth_date=int(api.world.clock.now().timestamp()))

    sent = await api.client.post(
        "/v1/id/telegram/otp/request",
        json={"init_data": init_data, "login": user.login},
    )
    linked = await api.client.post(
        "/v1/id/telegram/login",
        json={
            "init_data": init_data,
            "login": user.login,
            "otp_code": api.world.otp.last("login").code,
        },
    )

    assert sent.status_code == 202 and sent.json() == {"sent": True}
    assert linked.json() == {"linked": True, "login": user.login}


async def test_telegram_otp_request_with_forged_init_data_is_401(api: Api) -> None:
    """ID-20."""
    response = await api.client.post(
        "/v1/id/telegram/otp/request", json={"init_data": "hash=bad", "login": "x.y"}
    )

    assert response.status_code == 401


# - - - Recovery - - -


async def test_password_recovery_round_trip(api: Api) -> None:
    """UF-ID-07: 202, 202, then 204."""
    user = await api.world.add_user()

    asked = await api.client.post(
        "/v1/id/recovery/password/request", json={"login_or_email": user.login}
    )
    unknown = await api.client.post(
        "/v1/id/recovery/password/request", json={"login_or_email": "nobody.here"}
    )
    done = await api.client.post(
        "/v1/id/recovery/password/confirm",
        json={
            "login_or_email": user.login,
            "code": api.world.otp.last("pw-reset").code,
            "new_password": "N3wStrongPass",
        },
    )

    assert (asked.status_code, unknown.status_code, done.status_code) == (202, 202, 204)
    assert done.content == b""


async def test_weak_new_password_is_422_with_the_broken_rules(api: Api) -> None:
    """ID-4: id/password-policy lists the rules."""
    user = await api.world.add_user()

    response = await api.client.post(
        "/v1/id/recovery/password/confirm",
        json={"login_or_email": user.login, "code": "123456", "new_password": "weak"},
    )

    assert response.status_code == 422
    assert error_type(response) == "id/password-policy"
    assert "id-password-too-short" in response.json()["params"]["errors"]


async def test_otp_recovery_round_trip_and_cancel(api: Api) -> None:
    """UF-ID-08: request (202), confirm ({effective_at}), cancel (204)."""
    user = await api.world.add_user(otp_enabled=True)
    api.world.add_link(user, 555)

    asked = await api.client.post(
        "/v1/id/recovery/otp/request", json={"login": user.login}
    )
    confirmed = await api.client.post(
        "/v1/id/recovery/otp/confirm",
        json={"login": user.login, "code": api.world.otp.last("otp-reset").code},
    )
    request_id = api.world.user(user.id).otp_reset_request_id
    cancelled = await api.client.post(
        "/v1/id/recovery/otp/cancel", json={"request_id": str(request_id)}
    )

    assert asked.status_code == 202
    expected = api.world.clock.now() + timedelta(hours=24)
    assert confirmed.json()["effective_at"].startswith(
        expected.strftime("%Y-%m-%dT%H:%M:%S")
    )
    assert cancelled.status_code == 204
    assert api.world.user(user.id).otp_reset_request_id is None


async def test_login_recovery_is_202_for_any_email(api: Api) -> None:
    """UF-ID-10."""
    user = await api.world.add_user()

    known = await api.client.post(
        "/v1/id/recovery/login", json={"email": user.recovery_email}
    )
    unknown = await api.client.post(
        "/v1/id/recovery/login", json={"email": "no@example.org"}
    )

    assert (known.status_code, unknown.status_code) == (202, 202)
    assert len(api.world.email.to(user.recovery_email, "login_reminder")) == 1


# - - - Activation and scopes - - -


async def test_activation_round_trip(api: Api) -> None:
    """UF-ID-13: info, email code, activation with redirect."""
    admin = await api.admin()
    created = await api.client.post(
        "/v1/admin/teachers",
        json={
            "last_name": "Kalandarova",
            "first_name": "Gavxar",
            "email": "t@example.org",
        },
    )
    token = created.json()["activation_url"].split("token=")[1]

    info = await api.client.get(f"/v1/id/activation/{token}")
    code_sent = await api.client.post(
        f"/v1/id/activation/{token}/email", json={"email": "me@example.org"}
    )
    done = await api.client.post(
        f"/v1/id/activation/{token}",
        json={
            "password": "N3wStrongPass",
            "email": "me@example.org",
            "email_code": api.world.email.last_code("me@example.org"),
        },
    )

    assert admin is not None
    assert info.json() == {
        "first_name": "Gavxar",
        "last_name": "Kalandarova",
        "login": "kalandarova.gavxar",
        "requires_otp": False,
    }
    assert code_sent.status_code == 202
    assert done.json() == {"redirect_to": "http://localhost:3003"}
    again = await api.client.get(f"/v1/id/activation/{token}")
    assert again.status_code == 410 and error_type(again) == "id/activation-invalid"


async def test_mcp_scope_catalog_is_public(api: Api) -> None:
    """MCP-8: ScopeCatalog."""
    response = await api.client.get("/v1/id/mcp-scopes")

    assert response.status_code == 200
    servers = {s["server"]: s for s in response.json()["servers"]}
    assert set(servers) == {"student", "lms", "admin"}
    assert servers["student"]["roles"] == ["student"]
    assert {"scope": "homework:read", "tools": ["get_homework"]} in servers["student"][
        "scopes"
    ]
    assert {"key": "grades", "scopes": ["marks:read", "attendance:read"]} in servers[
        "student"
    ]["presets"]
