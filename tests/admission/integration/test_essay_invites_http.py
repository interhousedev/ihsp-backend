"""Essay review links over real HTTP and PostgreSQL."""

import datetime as dt

from app.shared.actor import Role
from tests.admission.integration.test_intl_http import (
    ESSAYS,
    _essay_student,
    _http,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI
from sqlalchemy import text

__all__ = ["clean_admission", "overrides_cleaned"]

PUBLIC = "/v1/public/admission/essay-review"
BODY = "I learned to listen. Then I learned to lead."
PRIVATE = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
    "x-robots-tag": "noindex",
}


def _private(headers: object) -> bool:
    return all(
        headers.get(k) == v for k, v in PRIVATE.items()  # type: ignore[attr-defined]
    )


async def test_guest_opens_comments_and_student_sees_it(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INV-30: a link opens without identity and the comment reaches the owner."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "inv.admin.open"
    )
    async with client:
        student, essay_id = await _essay_student(
            container, client, switch, "inv.student.open", BODY
        )
        made = await client.post(
            f"{ESSAYS}/{essay_id}/invites", json={"audience": "parent", "label": "Mum"}
        )
        assert made.status_code == 201, made.text
        token = made.json()["token"]

        opened = await client.post(f"{PUBLIC}/open", json={"token": token})
        assert opened.status_code == 200, opened.text
        assert _private(opened.headers)
        payload = opened.json()
        assert payload["essay"]["body"] == BODY
        assert str(student.user_id) not in opened.text
        assert {"id", "student_id", "label"}.isdisjoint(payload["essay"].keys())
        assert "label" not in payload

        start = BODY.index("listen")
        said = await client.post(
            f"{PUBLIC}/comments",
            json={
                "token": token,
                "author_name": "Mum",
                "body": "Lovely",
                "quote": "listen",
                "anchor_start": start,
                "anchor_end": start + 6,
            },
        )
        assert said.status_code == 201, said.text
        assert _private(said.headers)

        seen = await client.get(f"{ESSAYS}/{essay_id}/feedback")
        assert seen.status_code == 200, seen.text
        (item,) = seen.json()["items"]
        assert item["invite_label"] == "Mum" and item["anchor_start"] == start


async def test_dead_and_read_only_links(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INV-31: dead links 404 with private headers; read-only links 403."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "inv.admin.dead"
    )
    async with client:
        _, essay_id = await _essay_student(
            container, client, switch, "inv.student.dead", BODY
        )
        unknown = await client.post(f"{PUBLIC}/open", json={"token": "nope"})
        assert unknown.status_code == 404, unknown.text
        assert _private(unknown.headers)

        made = await client.post(
            f"{ESSAYS}/{essay_id}/invites",
            json={"audience": "classmate", "can_comment": False},
        )
        token, invite_id = made.json()["token"], made.json()["id"]
        denied = await client.post(
            f"{PUBLIC}/comments",
            json={"token": token, "author_name": "Sam", "body": "Hi"},
        )
        assert denied.status_code == 403, denied.text

        gone = await client.delete(f"{ESSAYS}/{essay_id}/invites/{invite_id}")
        assert gone.status_code == 204, gone.text
        revoked = await client.post(f"{PUBLIC}/open", json={"token": token})
        assert revoked.status_code == 404, revoked.text
        assert revoked.json()["type"] == unknown.json()["type"]


async def test_foreign_essay_is_not_found(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INV-32: another student cannot invite to or read feedback of my essay."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "inv.admin.idor"
    )
    async with client:
        _, essay_id = await _essay_student(
            container, client, switch, "inv.student.owner", BODY
        )
        await _essay_student(container, client, switch, "inv.student.thief", BODY)
        made = await client.post(
            f"{ESSAYS}/{essay_id}/invites", json={"audience": "parent"}
        )
        assert made.status_code == 404, made.text
        read = await client.get(f"{ESSAYS}/{essay_id}/feedback")
        assert read.status_code == 404, read.text


async def test_ttl_bounds_list_and_foreign_revoke(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INV-HTTP-40: ttl is 1..90 days; strangers cannot list or revoke (404)."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "inv.admin.ttl"
    )
    async with client:
        owner, essay_id = await _essay_student(
            container, client, switch, "inv.student.ttl", BODY
        )
        for days in (0, 91):
            bad = await client.post(
                f"{ESSAYS}/{essay_id}/invites",
                json={"audience": "parent", "ttl_days": days},
            )
            assert bad.status_code == 422, bad.text
        for days in (1, 90):
            ok = await client.post(
                f"{ESSAYS}/{essay_id}/invites",
                json={"audience": "parent", "ttl_days": days},
            )
            assert ok.status_code == 201, ok.text
        invite_id = ok.json()["id"]
        listed = await client.get(f"{ESSAYS}/{essay_id}/invites")
        assert listed.status_code == 200 and "token" not in listed.text

        await _essay_student(container, client, switch, "inv.student.peek", BODY)
        assert (await client.get(f"{ESSAYS}/{essay_id}/invites")).status_code == 404
        gone = await client.delete(f"{ESSAYS}/{essay_id}/invites/{invite_id}")
        assert gone.status_code == 404, gone.text
        switch.set(owner)
        still = await client.post(f"{PUBLIC}/open", json={"token": ok.json()["token"]})
        assert still.status_code == 200, still.text


async def test_expired_link_is_not_found(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INV-HTTP-41: an expired link answers like an unknown one."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "inv.admin.exp"
    )
    async with client:
        _, essay_id = await _essay_student(
            container, client, switch, "inv.student.exp", BODY
        )
        made = await client.post(
            f"{ESSAYS}/{essay_id}/invites", json={"audience": "parent"}
        )
        token = made.json()["token"]
        async with container.sessionmaker() as session, session.begin():
            await session.execute(
                text("UPDATE admission.essay_invites SET expires_at = :past"),
                {"past": container.clock.now() - dt.timedelta(days=1)},
            )
        expired = await client.post(f"{PUBLIC}/open", json={"token": token})
        assert expired.status_code == 404, expired.text
        assert _private(expired.headers)


async def test_twenty_comments_per_hour_per_link(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INV-HTTP-42: the 21st comment through one link is rate limited."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "inv.admin.rate"
    )
    async with client:
        _, essay_id = await _essay_student(
            container, client, switch, "inv.student.rate", BODY
        )
        made = await client.post(
            f"{ESSAYS}/{essay_id}/invites", json={"audience": "parent"}
        )
        token = made.json()["token"]
        sent = {"token": token, "author_name": "Mum", "body": "Nice"}
        for _ in range(20):
            ok = await client.post(f"{PUBLIC}/comments", json=sent)
            assert ok.status_code == 201, ok.text
        limited = await client.post(f"{PUBLIC}/comments", json=sent)
        assert limited.status_code == 429, limited.text
