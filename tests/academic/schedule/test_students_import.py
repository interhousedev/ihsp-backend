"""Student list and CSV import (ADM-3, ADM-17, ACA-18, UF-ADM-14)."""

import json

from app.modules.academic.domain.schedule.errors import (
    ImportExpiredError,
    ImportInvalidError,
)
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from tests.academic.schedule.env import Env
from tests.factories import make_actor

import pytest

ADMIN = make_actor(Role.ADMIN)
HEADER = "last_name,first_name,middle_name,group,emis_student_id\n"


async def test_students_are_listed_with_names_and_registration(env: Env) -> None:
    """ADM-3: the list shows names, group, subgroup and whether they registered."""
    group = await env.group("2TN2")
    await env.student(group, subgroup=1, first_name="Aliya", last_name="Aliyeva")
    await env.student(
        group,
        first_name="Bobur",
        last_name="Boburov",
        user_status=UserStatus.UNREGISTERED,
    )

    page = await env.services.list_students.execute()

    assert [
        (s.last_name, s.group_name, s.subgroup, s.registered) for s in page.items
    ] == [
        ("Aliyeva", "2TN2", 1, True),
        ("Boburov", "2TN2", None, False),
    ]
    assert page.next_cursor is None


async def test_students_can_be_filtered(env: Env) -> None:
    """ADM-3: search by name, group, subgroup, status, EMIS status, registration."""
    first = await env.group("2TN1")
    second = await env.group("2TN2")
    await env.student(first, subgroup=1, first_name="Aliya", last_name="Aliyeva")
    await env.student(second, subgroup=2, first_name="Bobur", last_name="Boburov")
    await env.student(second, last_name="Gone", first_name="Gulom", status="left")
    await env.student(
        second,
        last_name="Ghost",
        first_name="Gala",
        user_status=UserStatus.UNREGISTERED,
    )
    lister = env.services.list_students

    by_name = await lister.execute(query="bobu")
    by_two_words = await lister.execute(query="boburov bobur")
    by_group = await lister.execute(group_id=first.id)
    by_subgroup = await lister.execute(subgroup=2)
    by_status = await lister.execute(status="left")
    unregistered = await lister.execute(registered=False)
    reauth = await lister.execute(emis_status="needs_reauth")

    assert [s.last_name for s in by_name.items] == ["Boburov"]
    assert [s.last_name for s in by_two_words.items] == ["Boburov"]
    assert [s.last_name for s in by_group.items] == ["Aliyeva"]
    assert [s.last_name for s in by_subgroup.items] == ["Boburov"]
    assert [s.last_name for s in by_status.items] == ["Gone"]
    assert [s.last_name for s in unregistered.items] == ["Ghost"]
    assert reauth.items == []


async def test_the_student_list_is_paged_by_name(env: Env) -> None:
    """API: cursor pagination."""
    group = await env.group()
    for last in ("Cc", "Aa", "Bb"):
        await env.student(group, last_name=last)

    first = await env.services.list_students.execute(limit=2)
    second = await env.services.list_students.execute(limit=2, cursor=first.next_cursor)

    assert [s.last_name for s in first.items] == ["Aa", "Bb"]
    assert first.next_cursor is not None
    assert [s.last_name for s in second.items] == ["Cc"]
    assert second.next_cursor is None


async def test_the_preview_classifies_rows_and_changes_nothing(env: Env) -> None:
    """UF-ADM-14 step 2: new, changed, unchanged and conflicting rows."""
    group = await env.group("2TN2")
    other = await env.group("2TN1")
    same = await env.student(group, first_name="Ivan", last_name="Ivanov")
    mover = await env.student(other, first_name="Petr", last_name="Petrov")
    csv = (
        HEADER
        + "IVANOV,IVAN,,2ТН2,\n"
        + "PETROV,PETR,,2ТН2,\n"
        + "SIDOROV,SIDOR,SIDOROVICH,2ТН2,777\n"
        + "SIDOROV,SIDOR,,2ТН2,\n"
        + ",NOBODY,,2ТН2,\n"
    )

    preview = await env.services.import_preview.execute(csv.encode())

    assert [
        (r.last_name, r.first_name, r.emis_student_id) for r in preview.changed
    ] == [("Petrov", "Petr", None)]
    assert preview.unchanged == 1
    assert [r.line for r in preview.conflicts] == [4, 5, 6]
    assert preview.new == []
    assert env.commands.created == []
    async with env.uow_factory() as uow:
        assert (await uow.students.get(same.id)) is not None
        moved = await uow.students.get(mover.id)
    assert moved is not None and moved.group_id == other.id


async def test_the_preview_keeps_emis_ids_and_lists_new_students(env: Env) -> None:
    """UF-ADM-14: EMIS ids are shown in the preview and used on confirmation."""
    await env.group("2TN2")
    csv = HEADER + "Sidorov,Sidor,Sidorovich,2ТН2,777\n"

    preview = await env.services.import_preview.execute(csv.encode())

    [row] = preview.new
    assert (row.line, row.group_name, row.emis_student_id, row.middle_name) == (
        2,
        "2TN2",
        777,
        "Sidorovich",
    )
    assert preview.changed == [] and preview.conflicts == [] and preview.unchanged == 0


async def test_the_preview_is_stored_in_redis_for_an_hour(env: Env) -> None:
    """Redis import:{id} with a one hour TTL."""
    preview = await env.services.import_preview.execute(
        (HEADER + "A,B,,2TN2,\n").encode()
    )

    raw = await env.redis.get(f"import:{preview.import_id}")
    ttl = await env.redis.ttl(f"import:{preview.import_id}")

    assert raw is not None and json.loads(raw)["rows"][0]["kind"] == "new"
    assert 3500 < ttl <= 3600


async def test_a_file_without_rows_is_rejected(env: Env) -> None:
    """ADM-17: an empty export is an error, not an empty preview."""
    with pytest.raises(ImportInvalidError):
        await env.services.import_preview.execute(HEADER.encode())


async def test_confirming_creates_groups_students_and_moves_changed_ones(
    env: Env,
) -> None:
    """UF-ADM-14 step 3: missing groups are created; students are 'not registered'."""
    old = await env.group("2TN2")
    mover = await env.student(old, subgroup=2, first_name="Petr", last_name="Petrov")
    csv = (
        HEADER
        + "SIDOROV,SIDOR,,3ТН1,777\n"
        + "ABDULLAEV,ALI,,2ТН2,\n"
        + "PETROV,PETR,,3ТН1,\n"
        + "PETROV,PETR,,3ТН1,\n"
    )
    preview = await env.services.import_preview.execute(csv.encode())

    result = await env.services.import_confirm.execute(ADMIN, preview.import_id)

    assert (result.created, result.updated, result.skipped) == (2, 0, 2)
    assert env.commands.created[0]["emis_student_id"] == 777
    assert [c["last_name"] for c in env.commands.created] == ["Sidorov", "Abdullaev"]
    async with env.uow_factory() as uow:
        new_group = await uow.groups.find_active_by_slug("3tn1")
        assert new_group is not None
        students = await uow.students.list_filtered(status="active")
        unchanged_mover = await uow.students.get(mover.id)
    by_user = {s.user_id: s for s in students}
    created_ids = [c["user_id"] for c in env.commands.created]
    assert by_user[created_ids[0]].group_id == new_group.id
    assert by_user[created_ids[0]].subgroup is None
    assert unchanged_mover is not None and unchanged_mover.group_id == old.id
    assert [a.type for a in env.audits] == ["students.imported"]


async def test_confirming_moves_a_changed_student_and_clears_the_subgroup(
    env: Env,
) -> None:
    """ACA-3: a student found in another group moves; the subgroup is cleared."""
    old = await env.group("2TN2")
    mover = await env.student(old, subgroup=2, first_name="Petr", last_name="Petrov")
    preview = await env.services.import_preview.execute(
        (HEADER + "PETROV,PETR,,3ТН1,\n").encode()
    )

    result = await env.services.import_confirm.execute(ADMIN, preview.import_id)

    assert (result.created, result.updated, result.skipped) == (0, 1, 0)
    async with env.uow_factory() as uow:
        student = await uow.students.get(mover.id)
        target = await uow.groups.find_active_by_slug("3tn1")
    assert student is not None and target is not None
    assert student.group_id == target.id and student.subgroup is None


async def test_imported_students_appear_as_not_registered_in_the_group(
    env: Env,
) -> None:
    """ACA-18: rosters include students who have not registered yet."""
    group = await env.group("2TN2")
    preview = await env.services.import_preview.execute(
        (HEADER + "SIDOROV,SIDOR,,2ТН2,\n").encode()
    )
    await env.services.import_confirm.execute(ADMIN, preview.import_id)

    detail = await env.services.get_group_detail.execute(ADMIN, group.id)

    assert [(s.last_name, s.registered) for s in detail.students] == [
        ("Sidorov", False)
    ]
    assert detail.unregistered_count == 1


async def test_a_preview_can_be_confirmed_only_once(env: Env) -> None:
    """UF-ADM-14: the preview is consumed by confirmation."""
    await env.group("2TN2")
    preview = await env.services.import_preview.execute(
        (HEADER + "SIDOROV,SIDOR,,2ТН2,\n").encode()
    )
    await env.services.import_confirm.execute(ADMIN, preview.import_id)

    with pytest.raises(ImportExpiredError):
        await env.services.import_confirm.execute(ADMIN, preview.import_id)
    assert len(env.commands.created) == 1


async def test_an_unknown_preview_is_expired(env: Env) -> None:
    """UF-ADM-14: an expired id answers 410."""
    with pytest.raises(ImportExpiredError) as caught:
        await env.services.import_confirm.execute(ADMIN, new_id())

    assert caught.value.status == 410
