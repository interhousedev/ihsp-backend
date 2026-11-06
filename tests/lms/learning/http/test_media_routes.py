"""MCP-B5: the media routes: same 404 everywhere, no token in the response headers."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.interfaces.http.dependencies import get_optional_actor
from app.interfaces.http.v1.lms_learning import ROUTERS
from app.modules.lms.domain.step_content import VideoBlock
from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.shared.actor import Actor
from app.shared.wiring import ModuleDeps
from tests.conftest import HttpClientFactory
from tests.lms.learning.builders import content, seed_course
from tests.lms.learning.fakes.identity import FakeIdentityDirectory
from tests.lms.learning.fakes.preview_revisions import FakePreviewRevisions

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

FILE_ID = uuid4()


class _Files:
    async def download_url(self, file_id: Any, **_: Any) -> str:  # noqa: ANN401
        return f"https://s3.test/{file_id}"


@pytest.fixture
def media(
    deps: ModuleDeps,
    identity: FakeIdentityDirectory,
    previews: FakePreviewRevisions,
) -> LearningServices:
    return build_learning(
        deps,
        identity=identity,
        preview_revisions=previews,
        files=_Files(),  # type: ignore[arg-type]
    )


@pytest.fixture
async def viewer_client(
    http_client: HttpClientFactory, media: LearningServices, caller: dict[str, Actor]
) -> AsyncClient:
    from app.interfaces.http.dependencies import get_actor

    client: AsyncClient = await http_client(
        ROUTERS,
        {
            get_optional_actor: lambda: caller.get("actor"),
            get_actor: lambda: caller["actor"],
        },
        lms=SimpleNamespace(learning=media),
    )
    return client


async def _token(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
) -> str:
    block: Any = VideoBlock(id="vid", source="upload", file_id=str(FILE_ID))
    course = await seed_course(maker, steps=[("v", content("Video", block))])
    await media.enroll_in_course.execute(student, course.id)
    issued = await media.issue_media_grant.execute(
        student, course.id, course.step("v").step_id, "vid"
    )
    assert issued.token is not None
    return issued.token


async def test_anonymous_redeem_returns_url_and_private_headers(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    viewer_client: AsyncClient,
) -> None:
    """MCP-B5: no sign-in is needed within the window; nothing may cache the answer."""
    token = await _token(maker, media, student)
    response = await viewer_client.post("/v1/lms/media/redeem", json={"token": token})
    assert response.status_code == 200
    assert response.json()["url"].endswith(str(FILE_ID))
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_denied_and_unknown_give_the_same_body(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    other_student: Actor,
    caller: dict[str, Actor],
    viewer_client: AsyncClient,
) -> None:
    """MCP-B5: a refusal says nothing about why."""
    token = await _token(maker, media, student)
    caller["actor"] = other_student
    denied = await viewer_client.post("/v1/lms/media/redeem", json={"token": token})
    unknown = await viewer_client.post("/v1/lms/media/redeem", json={"token": "nope"})
    assert denied.status_code == unknown.status_code == 404
    for response in (denied, unknown):
        assert response.json()["type"].endswith("lms/media-not-available")
    assert denied.json().get("detail") == unknown.json().get("detail")
    assert "course" not in denied.text


async def test_grants_are_listed_and_revoked_by_the_issuer(
    maker: async_sessionmaker[AsyncSession],
    media: LearningServices,
    student: Actor,
    other_student: Actor,
    caller: dict[str, Actor],
    viewer_client: AsyncClient,
) -> None:
    """MCP-B5: a student sees and stops their own links, nobody else's."""
    token = await _token(maker, media, student)
    caller["actor"] = student
    listed = (await viewer_client.get("/v1/lms/media/grants")).json()
    assert len(listed["items"]) == 1
    assert "token" not in str(listed).replace("token_hash", "x") or token not in str(
        listed
    )
    grant_id = listed["items"][0]["id"]
    caller["actor"] = other_student
    refused = await viewer_client.delete(f"/v1/lms/media/grants/{grant_id}")
    assert refused.status_code == 404
    caller["actor"] = student
    done = await viewer_client.delete(f"/v1/lms/media/grants/{grant_id}")
    assert done.status_code == 204
    gone = await viewer_client.post("/v1/lms/media/redeem", json={"token": token})
    assert gone.status_code == 404
