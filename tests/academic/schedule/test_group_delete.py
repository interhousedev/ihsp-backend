"""DELETE /v1/admin/groups/{id}: students are detached, entries cleaned up."""

import uuid

from app.modules.academic.domain import audience as audience_keys
from app.shared.actor import Role
from tests.academic.schedule.conftest import Api
from tests.academic.schedule.env import Env


async def test_deleting_a_group_detaches_its_students(env: Env, api: Api) -> None:
    """204, then the group is gone and its students are groupless, not deleted."""
    group = await env.group("2TN2")
    pupil = await env.student(group, subgroup=1)

    response = await api.client.delete(f"/v1/admin/groups/{group.id}")

    assert response.status_code == 204
    gone = await api.client.get(f"/v1/admin/groups/{group.id}")
    assert gone.status_code == 404
    assert gone.json()["type"] == "academic/group-not-found"
    async with env.uow_factory() as uow:
        student = await uow.students.get(pupil.id)
    assert student is not None
    assert student.group_id is None
    assert student.subgroup is None
    audit = next(a for a in env.audits if a.type == "group.deleted")
    assert audit.metadata["student_ids"] == [str(pupil.id)]
    assert audit.metadata["student_count"] == 1


async def test_deleting_a_group_cleans_its_timetable_entries(
    env: Env, api: Api
) -> None:
    """Own entries are removed; a shared entry loses only this group's keys."""
    group = await env.group("2TN2")
    other = await env.group("2TN3")
    term = await env.term()
    subject = await env.subject()
    own = await env.entry(
        term,
        weekday=1,
        period=1,
        subject=subject,
        audience=[audience_keys.key(group.id, None)],
    )
    shared = await env.entry(
        term,
        weekday=2,
        period=1,
        subject=subject,
        audience=[audience_keys.key(group.id, None), audience_keys.key(other.id, None)],
    )

    response = await api.client.delete(f"/v1/admin/groups/{group.id}")

    assert response.status_code == 204
    async with env.uow_factory() as uow:
        assert await uow.entries.get(own.id) is None
        kept = await uow.entries.get(shared.id)
    assert kept is not None
    assert kept.audience == [audience_keys.key(other.id, None)]


async def test_a_non_admin_cannot_delete_a_group(env: Env, api: Api) -> None:
    """Only administrators delete groups."""
    group = await env.group("2TN2")
    api.as_role(Role.TEACHER)

    response = await api.client.delete(f"/v1/admin/groups/{group.id}")

    assert response.status_code == 403


async def test_deleting_an_unknown_group_answers_404(env: Env, api: Api) -> None:
    """A missing group is not found."""
    response = await api.client.delete(f"/v1/admin/groups/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["type"] == "academic/group-not-found"
