"""Calendar token use cases and their adapter: fakes and PostgreSQL (WEB-6)."""

from uuid import UUID

from app.bootstrap.adapters.composition.calendar_token_store import (
    CalendarTokenStoreAdapter,
)
from app.modules.academic.infrastructure.orm import Student as StudentRow
from app.shared.ids import hash_token, new_id, random_token
from tests.academic.schedule.env import Env

import sqlalchemy as sa


async def stored_hash(env: Env, user_id: UUID) -> str | None:
    """Read `academic.students.calendar_token_hash` straight from the storage."""
    if env.store is not None:
        return env.store.calendar_tokens.get(user_id)
    assert env.maker is not None
    async with env.maker() as session:
        return await session.scalar(
            sa.select(StudentRow.calendar_token_hash).where(
                StudentRow.user_id == user_id
            )
        )


async def test_rotate_stores_the_hash_and_finds_the_owner(env: Env) -> None:
    """The hash is written to the student and resolves back to the student."""
    student = await env.student(await env.group())
    digest = hash_token(random_token())

    stored = await env.services.rotate_calendar_token.execute(student.id, digest)

    assert stored is True
    assert await stored_hash(env, student.id) == digest
    assert await env.services.user_for_calendar_token.execute(digest) == student.id


async def test_rotate_replaces_the_old_token(env: Env) -> None:
    """After a rotation the old feed URL stops working (WEB-6)."""
    student = await env.student(await env.group())
    old, new = hash_token("old-token"), hash_token("new-token")
    await env.services.rotate_calendar_token.execute(student.id, old)

    await env.services.rotate_calendar_token.execute(student.id, new)

    lookup = env.services.user_for_calendar_token
    assert await lookup.execute(old) is None
    assert await lookup.execute(new) == student.id


async def test_rotate_reports_a_user_without_a_student_record(env: Env) -> None:
    """A teacher or a stranger has no feed: rotate returns False and stores nothing."""
    digest = hash_token("token")

    stored = await env.services.rotate_calendar_token.execute(new_id(), digest)

    assert stored is False
    assert await env.services.user_for_calendar_token.execute(digest) is None


async def test_each_student_resolves_to_their_own_token(env: Env) -> None:
    """Two students never see each other's feed."""
    group = await env.group()
    first = await env.student(group, first_name="Aziza", last_name="Karimova")
    second = await env.student(group, first_name="Bobur", last_name="Aliyev")
    first_hash, second_hash = hash_token("first"), hash_token("second")
    await env.services.rotate_calendar_token.execute(first.id, first_hash)
    await env.services.rotate_calendar_token.execute(second.id, second_hash)

    lookup = env.services.user_for_calendar_token
    assert await lookup.execute(first_hash) == first.id
    assert await lookup.execute(second_hash) == second.id


async def test_a_student_who_left_has_no_feed(env: Env) -> None:
    """Only active students own a token (the port's contract)."""
    student = await env.student(await env.group(), status="left")
    digest = hash_token("token")
    await env.services.rotate_calendar_token.execute(student.id, digest)

    assert await env.services.user_for_calendar_token.execute(digest) is None


async def test_an_unknown_hash_belongs_to_nobody(env: Env) -> None:
    """Unknown tokens resolve to None."""
    lookup = env.services.user_for_calendar_token

    assert await lookup.execute(hash_token("nobody")) is None


async def test_the_adapter_delegates_to_the_use_cases(env: Env) -> None:
    """`CalendarTokenStore.rotate` / `user_for_token` over the real use cases."""
    store = CalendarTokenStoreAdapter(
        env.services.rotate_calendar_token, env.services.user_for_calendar_token
    )
    student = await env.student(await env.group())
    digest = hash_token("token")

    assert await store.rotate(student.id, digest) is True
    assert await store.user_for_token(digest) == student.id
    assert await store.rotate(new_id(), hash_token("other")) is False
    assert await store.user_for_token(hash_token("other")) is None
