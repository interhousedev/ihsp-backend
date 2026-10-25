"""HTTP contract of course authoring (§ API contract, LMS rows of task B12)."""

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.lms_authoring import ROUTERS
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.actor import Actor, Role
from tests.conftest import HttpClientFactory
from tests.fakes.lms.identity import FakeIdentityDirectory
from tests.lms.authoring.conftest import CourseFixture

import pytest
from httpx import AsyncClient

PROBLEM = "application/problem+json"


@dataclass(slots=True)
class Api:
    """A client whose caller can be switched between requests."""

    client: AsyncClient
    switch: SimpleNamespace

    def as_(self, actor: Actor) -> AsyncClient:
        """Make the next requests as this actor."""
        self.switch.actor = actor
        return self.client


@pytest.fixture
async def api(
    http_client: HttpClientFactory,
    services: AuthoringServices,
    identity: FakeIdentityDirectory,
    admin: Actor,
) -> Api:
    """The authoring routers over the real services; the actor is overridable."""
    switch = SimpleNamespace(actor=admin)
    client = await http_client(
        ROUTERS,
        {get_actor: lambda: switch.actor},
        lms=SimpleNamespace(authoring=services),
        identity=identity,
    )
    return Api(client, switch)


def _text(markdown: str) -> dict[str, Any]:
    return {"type": "text", "markdown": markdown}


async def test_the_whole_authoring_flow_over_http(
    api: Api,
    admin: Actor,
    make_actor: Callable[..., Actor],
    identity: FakeIdentityDirectory,
) -> None:
    """UF-LMS-06, UF-LMS-08, UF-LMS-10, UF-LMS-11: create, edit, publish, browse."""
    teacher = make_actor(Role.TEACHER)
    identity.add_user("madina", user_id=teacher.user_id, first_name="Madina")
    client = api.as_(admin)

    created = await client.post(
        "/v1/lms/courses",
        json={"title": "Calculus", "slug": "calculus", "visibility": "invite"},
    )
    course_id = created.json()["id"]
    staff = await client.post(
        f"/v1/lms/courses/{course_id}/staff",
        json={
            "login": "madina",
            "role": "Teacher",
            "permissions": ["edit", "publish", "review", "view_drafts"],
            "show_on_page": True,
            "position": 0,
        },
    )
    client = api.as_(teacher)
    outline = await client.post(
        f"/v1/lms/courses/{course_id}/draft/outline",
        json={"ops": [{"op": "add_section", "title": "Limits"}], "lock_version": 0},
    )
    section_id = outline.json()["outline"][0]["id"]
    step = await client.post(
        f"/v1/lms/courses/{course_id}/steps",
        json={"section_id": section_id, "title": "Intro"},
    )
    step_id = step.json()["step_id"]
    saved = await client.put(
        f"/v1/lms/steps/{step_id}/draft",
        json={
            "content": {"title": "Intro", "blocks": [_text("Hello")]},
            "lock_version": step.json()["lock_version"],
        },
    )
    pending = await client.get(f"/v1/lms/courses/{course_id}/pending")
    published = await client.post(
        f"/v1/lms/courses/{course_id}/publish",
        json={"draft_seq": pending.json()["draft_seq"], "note": "First"},
    )
    versions = await client.get(f"/v1/lms/courses/{course_id}/versions")
    version = await client.get(f"/v1/lms/courses/{course_id}/versions/1")
    draft = await client.get(f"/v1/lms/courses/{course_id}/draft")

    assert created.status_code == 200
    assert created.json()["invite_code"] and created.json()["live_version"] is None
    assert staff.json()["user"]["first_name"] == "Madina"
    assert outline.json()["lock_version"] == 1
    assert saved.json()["content"]["blocks"][0]["id"]
    assert saved.json()["status"] == "new"
    assert pending.json()["steps"] == [
        {
            "step_id": step_id,
            "title": "Intro",
            "change": "added",
            "via_mcp": False,
            "via_ai": False,
        }
    ]
    assert published.json()["number"] == 1 and published.json()["note"] == "First"
    assert published.json()["changes"] == {
        "added": 1,
        "changed": 0,
        "removed": 0,
        "outline_changed": True,
    }
    assert [v["number"] for v in versions.json()] == [1]
    assert version.json()["meta"] == {"title": "Calculus", "description": ""}
    assert version.json()["outline"][0]["steps"][0]["title"] == "Intro"
    assert draft.json()["live_version"] == 1 and draft.json()["pending_count"] == 0
    assert "my_permissions" in draft.json()


async def test_stale_step_save_is_a_409_problem_with_their_version(
    api: Api, course: CourseFixture
) -> None:
    """§ API contract: `PUT /steps/{id}/draft` → `409 {params: {theirs: StepDraft}}`."""
    owner, teacher = course.team.owner, course.team.teacher
    client = api.as_(owner)
    section = (
        await client.post(
            f"/v1/lms/courses/{course.id}/draft/outline",
            json={"ops": [{"op": "add_section", "title": "S"}], "lock_version": 0},
        )
    ).json()["outline"][0]["id"]
    step = (
        await client.post(
            f"/v1/lms/courses/{course.id}/steps",
            json={"section_id": section, "title": "Intro"},
        )
    ).json()
    await client.put(
        f"/v1/lms/steps/{step['step_id']}/draft",
        json={
            "content": {"title": "Intro", "blocks": [_text("Mine")]},
            "lock_version": 0,
        },
    )

    response = await api.as_(teacher).put(
        f"/v1/lms/steps/{step['step_id']}/draft",
        json={
            "content": {"title": "Intro", "blocks": [_text("Theirs")]},
            "lock_version": 0,
        },
    )

    body = response.json()
    assert response.status_code == 409
    assert response.headers["content-type"].startswith(PROBLEM)
    assert body["type"] == "common/conflict"
    assert body["params"]["theirs"]["content"]["blocks"][0]["markdown"] == "Mine"
    assert body["params"]["theirs"]["lock_version"] == 1


async def test_publishing_with_an_old_draft_seq_is_409_draft_changed(
    api: Api, course: CourseFixture
) -> None:
    """§ API contract: `409` if `draft_seq` changed; error type `lms/draft-changed`."""
    client = api.as_(course.team.owner)
    await client.post(
        f"/v1/lms/courses/{course.id}/draft/outline",
        json={"ops": [{"op": "add_section", "title": "S"}], "lock_version": 0},
    )

    response = await client.post(
        f"/v1/lms/courses/{course.id}/publish", json={"draft_seq": 0}
    )

    assert response.status_code == 409
    assert response.json()["type"] == "lms/draft-changed"


async def test_unknown_login_is_404_user_not_found(
    api: Api, course: CourseFixture
) -> None:
    """§ API contract: unknown login → `404 id/user-not-found`."""
    response = await api.as_(course.team.admin).post(
        f"/v1/lms/courses/{course.id}/staff",
        json={"login": "ghost", "role": "Tester", "permissions": ["view_drafts"]},
    )

    assert response.status_code == 404
    assert response.json()["type"] == "id/user-not-found"


async def test_permissions_are_enforced_and_reported_as_403(
    api: Api, course: CourseFixture
) -> None:
    """A tester reads the draft but cannot change it."""
    client = api.as_(course.team.tester)

    read = await client.get(f"/v1/lms/courses/{course.id}/draft")
    write = await client.put(
        f"/v1/lms/courses/{course.id}/draft/meta",
        json={"title": "Hacked", "description": "", "lock_version": 0},
    )
    outsider = await api.as_(course.team.outsider).get(
        f"/v1/lms/courses/{course.id}/draft"
    )

    assert read.status_code == 200
    assert write.status_code == 403
    assert write.json()["type"] == "lms/permission-denied"
    assert outsider.status_code == 403


async def test_validation_errors_are_422(api: Api, admin: Actor) -> None:
    """Bodies are validated; bad outline operations and slugs are 422."""
    client = api.as_(admin)

    bad_slug = await client.post(
        "/v1/lms/courses",
        json={"title": "X", "slug": "Bad Slug!", "visibility": "public"},
    )
    bad_op = await client.post(
        "/v1/lms/courses",
        json={"title": "X", "slug": "good-slug", "visibility": "public"},
    )
    response = await client.post(
        f"/v1/lms/courses/{bad_op.json()['id']}/draft/outline",
        json={"ops": [{"op": "explode"}], "lock_version": 0},
    )

    assert bad_slug.status_code == 422
    assert response.status_code == 422


async def test_staff_endpoints_list_update_and_delete(
    api: Api, course: CourseFixture
) -> None:
    """LMS-5: list, patch and remove course staff."""
    client = api.as_(course.team.owner)
    tester = str(course.team.tester.user_id)

    listing = await client.get(f"/v1/lms/courses/{course.id}/staff")
    patched = await client.patch(
        f"/v1/lms/courses/{course.id}/staff/{tester}",
        json={"role": "QA", "show_on_page": False},
    )
    deleted = await client.delete(f"/v1/lms/courses/{course.id}/staff/{tester}")
    last = await client.delete(
        f"/v1/lms/courses/{course.id}/staff/{course.team.owner.user_id}"
    )

    assert {i["role"] for i in listing.json()} == {
        "Owner",
        "Teacher",
        "Tester",
        "Reviewer",
    }
    assert patched.json()["role"] == "QA" and patched.json()["show_on_page"] is False
    assert deleted.status_code == 204 and deleted.content == b""
    assert last.status_code == 409
    assert last.json()["type"] == "lms/last-manager"


async def test_settings_and_invite_code_endpoints(
    api: Api, course: CourseFixture
) -> None:
    """LMS-3: visibility, status and the invite code."""
    client = api.as_(course.team.owner)

    patched = await client.patch(
        f"/v1/lms/courses/{course.id}/settings",
        json={"visibility": "invite", "status": "archived"},
    )
    rotated = await client.post(f"/v1/lms/courses/{course.id}/invite-code")

    assert patched.json()["visibility"] == "invite"
    assert patched.json()["status"] == "archived"
    assert rotated.json()["invite_code"] != patched.json()["invite_code"]
    assert len(rotated.json()["invite_code"]) == 10


async def test_checkpoint_history_restore_and_diff_endpoints(
    api: Api, course: CourseFixture
) -> None:
    """LMS-12: checkpoints, history, restore, diff."""
    client = api.as_(course.team.owner)
    section = (
        await client.post(
            f"/v1/lms/courses/{course.id}/draft/outline",
            json={"ops": [{"op": "add_section", "title": "S"}], "lock_version": 0},
        )
    ).json()["outline"][0]["id"]
    step = (
        await client.post(
            f"/v1/lms/courses/{course.id}/steps",
            json={"section_id": section, "title": "Intro"},
        )
    ).json()
    sid = step["step_id"]
    good = (
        await client.put(
            f"/v1/lms/steps/{sid}/draft",
            json={
                "content": {"title": "Intro", "blocks": [_text("good")]},
                "lock_version": 0,
            },
        )
    ).json()
    checkpoint = await client.post(
        f"/v1/lms/steps/{sid}/checkpoints", json={"label": "good"}
    )
    await client.put(
        f"/v1/lms/steps/{sid}/draft",
        json={
            "content": {"title": "Intro", "blocks": [_text("bad")]},
            "lock_version": good["lock_version"],
        },
    )

    history = await client.get(f"/v1/lms/steps/{sid}/history")
    diff = await client.get(f"/v1/lms/steps/{sid}/diff")
    restored = await client.post(
        f"/v1/lms/steps/{sid}/restore", json={"revision_id": checkpoint.json()["id"]}
    )

    assert (
        checkpoint.json()["kind"] == "checkpoint"
        and checkpoint.json()["label"] == "good"
    )
    assert [h["id"] for h in history.json()] == [checkpoint.json()["id"]]
    assert diff.json()["live"] is None
    assert diff.json()["draft"]["blocks"][0]["markdown"] == "bad"
    assert restored.json()["content"]["blocks"][0]["markdown"] == "good"


async def test_versions_compare_restore_discard_and_preview_endpoints(
    api: Api, course: CourseFixture
) -> None:
    """LMS-8, LMS-10, LMS-11: compare, restore, discard and preview."""
    client = api.as_(course.team.owner)
    cid = str(course.id)
    section = (
        await client.post(
            f"/v1/lms/courses/{cid}/draft/outline",
            json={"ops": [{"op": "add_section", "title": "S"}], "lock_version": 0},
        )
    ).json()["outline"][0]["id"]
    step = (
        await client.post(
            f"/v1/lms/courses/{cid}/steps",
            json={"section_id": section, "title": "Intro"},
        )
    ).json()
    sid = step["step_id"]
    await client.put(
        f"/v1/lms/steps/{sid}/draft",
        json={
            "content": {"title": "Intro", "blocks": [_text("v1")]},
            "lock_version": 0,
        },
    )
    seq = (await client.get(f"/v1/lms/courses/{cid}/pending")).json()["draft_seq"]
    await client.post(f"/v1/lms/courses/{cid}/publish", json={"draft_seq": seq})
    await client.put(
        f"/v1/lms/steps/{sid}/draft",
        json={
            "content": {"title": "Intro", "blocks": [_text("v2")]},
            "lock_version": 1,
        },
    )
    seq = (await client.get(f"/v1/lms/courses/{cid}/pending")).json()["draft_seq"]
    await client.post(f"/v1/lms/courses/{cid}/publish", json={"draft_seq": seq})

    compare = await client.get(
        f"/v1/lms/courses/{cid}/compare", params={"a": 1, "b": 2}
    )
    restored = await client.post(f"/v1/lms/courses/{cid}/versions/1/restore")
    preview = await api.as_(course.team.tester).get(
        f"/v1/lms/courses/{cid}/preview/steps/{sid}"
    )
    discarded = await api.as_(course.team.owner).post(f"/v1/lms/courses/{cid}/discard")
    missing = await client.get(f"/v1/lms/courses/{cid}/versions/9")

    assert compare.json()["a"] == 1 and compare.json()["b"] == 2
    assert [(s["title"], s["change"]) for s in compare.json()["steps"]] == [
        ("Intro", "changed")
    ]
    assert restored.json()["pending_count"] == 1
    assert preview.json()["preview"] is True
    assert preview.json()["blocks"][0]["markdown"] == "v1"
    assert discarded.json()["pending_count"] == 0
    assert missing.status_code == 404
    assert missing.json()["type"] == "lms/version-not-found"


async def test_step_discard_endpoint(api: Api, course: CourseFixture) -> None:
    """LMS-10: discard the pending changes of one step."""
    client = api.as_(course.team.owner)
    cid = str(course.id)
    section = (
        await client.post(
            f"/v1/lms/courses/{cid}/draft/outline",
            json={"ops": [{"op": "add_section", "title": "S"}], "lock_version": 0},
        )
    ).json()["outline"][0]["id"]
    sid = (
        await client.post(
            f"/v1/lms/courses/{cid}/steps",
            json={"section_id": section, "title": "Intro"},
        )
    ).json()["step_id"]

    new_step = await client.post(f"/v1/lms/steps/{sid}/discard")

    assert new_step.status_code == 422
    assert new_step.json()["type"] == "lms/no-live-version"


async def test_saving_with_empty_ids_gets_server_ids(
    api: Api, course: CourseFixture
) -> None:
    """LMS-23: the editor sends `""` for new items; the response carries real IDs."""
    client = api.as_(course.team.owner)
    section = (
        await client.post(
            f"/v1/lms/courses/{course.id}/draft/outline",
            json={"ops": [{"op": "add_section", "title": "S"}], "lock_version": 0},
        )
    ).json()["outline"][0]["id"]
    step = (
        await client.post(
            f"/v1/lms/courses/{course.id}/steps",
            json={"section_id": section, "title": "Intro"},
        )
    ).json()

    saved = await client.put(
        f"/v1/lms/steps/{step['step_id']}/draft",
        json={
            "content": {
                "title": "Intro",
                "blocks": [
                    {"id": "", "type": "text", "markdown": "A"},
                    {"id": "", "type": "text", "markdown": "B"},
                ],
            },
            "lock_version": 0,
        },
    )

    ids = [b["id"] for b in saved.json()["content"]["blocks"]]
    assert saved.status_code == 200
    assert all(len(i) == 8 for i in ids) and len(set(ids)) == 2
