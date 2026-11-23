"""Trajectories over real HTTP and PostgreSQL: curator editor, student progress."""

from app.modules.admission.infrastructure.orm.access import EntitlementRow
from app.shared.actor import Role
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    _user,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI

STAFF = "/v1/admission/staff/trajectories"
PUBLIC = "/v1/admission/trajectories"


def _node(nid: str, optional: bool = False) -> dict[str, object]:
    return {
        "id": nid,
        "title": {"en": nid, "ru": nid, "uz": nid},
        "kind": "topic",
        "level": "beginner",
        "description": {"en": "", "ru": "", "uz": ""},
        "optional": optional,
        "resources": [{"kind": "url", "ref": "https://example.org/x", "title": "Read"}],
    }


BODY = {
    "slug": "it-test-path",
    "field": "cs_it",
    "title": {"en": "Test path", "ru": "", "uz": ""},
    "description": {"en": "", "ru": "", "uz": ""},
    "published": True,
    "stages": [
        {"id": "s1", "title": {"en": "One", "ru": "", "uz": ""}, "nodes": [_node("a")]},
        {
            "id": "s2",
            "title": {"en": "Two", "ru": "", "uz": ""},
            "nodes": [_node("b"), _node("c", True)],
        },
    ],
    "edges": [{"before": "a", "after": "b"}],
}


async def test_curator_edits_and_student_tracks_progress(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]  # noqa: F811
) -> None:
    """Cycles are refused; the student marks nodes; delete cascades progress."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "tr.admin"
    )
    async with client:
        made = await client.post(STAFF, json=BODY)
        assert made.status_code == 201, made.text
        tid = made.json()["id"]
        assert made.json()["stages"][1]["nodes"][0]["position"] == 0
        cyclic = {
            **BODY,
            "slug": "it-cyclic",
            "edges": [{"before": "a", "after": "b"}, {"before": "b", "after": "a"}],
        }
        bad = await client.post(STAFF, json=cyclic)
        assert bad.status_code == 422, bad.text
        assert (await client.post(STAFF, json=BODY)).status_code == 422

        student = await _user(container, "tr.student", Role.STUDENT)
        async with container.sessionmaker() as session, session.begin():
            session.add(
                EntitlementRow(
                    user_id=student.user_id,
                    kind="school_student",
                    cohort_year=None,
                    granted_by=None,
                )
            )
        switch.set(student)
        listed = await client.get(PUBLIC, params={"field": "cs_it", "q": "test"})
        assert listed.status_code == 200, listed.text
        [item] = [i for i in listed.json()["items"] if i["id"] == tid]
        assert (item["required_count"], item["done_count"]) == (2, 0)
        marked = await client.put(f"{PUBLIC}/{tid}/progress/a", json={"status": "done"})
        assert marked.status_code == 200, marked.text
        assert marked.json()["progress"] == [{"node_id": "a", "status": "done"}]
        opened = await client.get(f"{PUBLIC}/it-test-path")
        assert opened.json()["can_track"] is True
        assert (await client.get(STAFF)).status_code in (403, 404)

        switch.set(await _user(container, "tr.admin2", Role.ADMIN))
        assert (await client.delete(f"{STAFF}/{tid}")).status_code == 204
        assert (await client.get(f"{STAFF}/{tid}")).status_code == 404
