"""HTTP: /v1/me/onboarding/* follows the API contract."""

from typing import Any
from uuid import UUID

from app.bootstrap.adapters.onboarding import OnboardingCertificatesAdapter
from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.onboarding import ROUTERS
from app.modules.onboarding.wiring import build
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.certificates.conftest import CertificatesHarness, h  # noqa: F401
from tests.fakes.clock import FixedClock
from tests.fakes.onboarding.uow import FakeOnboardingStore, FakeOnboardingUow
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _Faces:
    """FaceGate: a fixed answer."""

    def __init__(self) -> None:
        """No photo yet."""
        self.has = False

    async def has_face(self, user_id: UUID) -> bool:
        """Return the fixed answer."""
        return self.has


class Api:
    """A client whose requests run as ``actor``."""

    def __init__(
        self,
        client: AsyncClient,
        actor: Actor,
        faces: _Faces,
        harness: CertificatesHarness,
    ) -> None:
        """Start as the given actor."""
        self.client, self.actor, self.faces, self.h = client, actor, faces, harness


@pytest.fixture
async def api(
    h: CertificatesHarness,  # noqa: F811
    http_client: Any,
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
) -> Api:
    """A client for the onboarding routes over the certificates module."""
    faces, store = _Faces(), FakeOnboardingStore()
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=async_sessionmaker(class_=AsyncSession),
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    services = build(
        deps,
        faces=faces,
        importer=OnboardingCertificatesAdapter(h.services.import_emis),
        uow_factory=lambda: FakeOnboardingUow(store),
    )
    holder: dict[str, Api] = {}
    client = await http_client(
        ROUTERS,
        {get_actor: lambda: holder["api"].actor},
        onboarding=services,
        certificates=h.services,
    )
    holder["api"] = Api(client, h.student_actor(h.ann), faces, h)
    return holder["api"]


async def test_get_lists_both_steps_for_a_new_student(api: Api) -> None:
    response = await api.client.get("/v1/me/onboarding")
    assert response.status_code == 200
    assert response.json() == {
        "required": True,
        "steps": [
            {"key": "selfie", "required": True, "done": False, "skippable": False},
            {
                "key": "certificates",
                "required": False,
                "done": False,
                "skippable": True,
            },
        ],
    }


async def test_done_hides_the_certificates_step(api: Api) -> None:
    api.faces.has = True
    response = await api.client.post("/v1/me/onboarding/certificates/done")
    assert response.status_code == 200
    assert response.json() == {"required": False, "steps": []}
    again = await api.client.get("/v1/me/onboarding")
    assert again.json() == {"required": False, "steps": []}


async def test_get_is_empty_for_a_teacher(api: Api) -> None:
    api.actor = api.h.admin
    response = await api.client.get("/v1/me/onboarding")
    assert response.status_code == 200
    assert response.json() == {"required": False, "steps": []}


async def test_post_is_forbidden_for_non_students(api: Api) -> None:
    api.actor = api.h.admin
    for path in ("done", "refresh-emis"):
        response = await api.client.post(f"/v1/me/onboarding/certificates/{path}")
        assert response.status_code == 403, response.text


async def test_refresh_returns_the_students_entries(api: Api) -> None:
    kind = await api.h.add_type("sat")
    await api.h.add_entry(api.h.ann, kind)  # one manual entry
    response = await api.client.post("/v1/me/onboarding/certificates/refresh-emis")
    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["type_id"] == str(kind.id)


async def test_refresh_is_rate_limited(api: Api) -> None:
    path = "/v1/me/onboarding/certificates/refresh-emis"
    for _ in range(3):
        assert (await api.client.post(path)).status_code == 200
    blocked = await api.client.post(path)
    assert blocked.status_code == 429, blocked.text
    assert blocked.headers["content-type"].startswith("application/problem+json")
