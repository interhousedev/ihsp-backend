"""EMIS facts of a group are stored when the profile is read, and overwritten by it."""

from app.shared.contracts.emis import EmisName, EmisProfile
from app.shared.ids import new_id
from tests.academic.schedule.env import Env


def _profile(**overrides: object) -> EmisProfile:
    fields: dict[str, object] = {
        "emis_student_id": 900001,
        "first_name": "Ali",
        "last_name": "Karimov",
        "middle_name": None,
        "institution_id": 10815,
        "group_emis_id": 3292,
        "group_name": "2TN2",
        "current_semester": 3,
        "curriculum_id": 555,
        "institution_name": EmisName(uz="Lits", ru="Лицей", en="Lyceum"),
        "direction": "Tabiiy fanlar",
        "speciality": "Informatika",
    }
    fields.update(overrides)
    return EmisProfile(**fields)  # type: ignore[arg-type]


async def test_emis_facts_are_stored_on_the_group(env: Env) -> None:
    """The group keeps the EMIS name, course, direction, speciality and institution."""
    ref = await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2ТН2",
        current_semester=3,
        curriculum_id=555,
    )

    await env.services.enrollment.record_emis_facts(
        group_id=ref.group_id, profile=_profile()
    )

    async with env.uow_factory() as uow:
        group = await uow.groups.get(ref.group_id)
    assert group is not None
    assert (
        group.emis_name,
        group.course,
        group.direction,
        group.speciality,
        group.institution_name,
    ) == (
        "2TN2",
        2,
        "Tabiiy fanlar",
        "Informatika",
        {"uz": "Lits", "ru": "Лицей", "en": "Lyceum"},
    )


async def test_a_later_profile_overwrites_the_stored_facts(env: Env) -> None:
    """A newer EMIS read replaces the stored facts (course moves on, name fixed)."""
    ref = await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2ТН2",
        current_semester=3,
        curriculum_id=555,
    )
    await env.services.enrollment.record_emis_facts(
        group_id=ref.group_id, profile=_profile()
    )

    await env.services.enrollment.record_emis_facts(
        group_id=ref.group_id,
        profile=_profile(
            current_semester=5,
            institution_name=None,
            direction=None,
        ),
    )

    async with env.uow_factory() as uow:
        group = await uow.groups.get(ref.group_id)
    assert group is not None
    assert (group.course, group.direction, group.institution_name) == (3, None, None)
