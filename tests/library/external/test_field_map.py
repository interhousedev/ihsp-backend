"""LIB-12: which UniLibrary field is which lyceum subject."""

from app.modules.library.domain.external_errors import FieldMapInvalidError
from app.modules.library.domain.external_feed import FieldMapEntry
from app.modules.library.wiring_external import ExternalServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.ids import new_id
from tests.fakes.library.academic import FakeAcademicDirectory

import pytest


async def test_the_map_is_empty_until_it_is_set(
    external: ExternalServices, admin: Actor
) -> None:
    """LIB-12: no seed rows are invented."""
    assert await external.get_field_map.execute(admin) == []


async def test_put_replaces_the_map_and_returns_it(
    external: ExternalServices, admin: Actor, academic: FakeAcademicDirectory
) -> None:
    """LIB-12: seed example: Physics 27, Mathematics 25."""
    physics = academic.add_subject(new_id(), "Physics")
    maths = academic.add_subject(new_id(), "Mathematics")

    saved = await external.put_field_map.execute(
        admin, [FieldMapEntry(physics, 27), FieldMapEntry(maths, 25)]
    )

    assert {(e.subject_id, e.external_field_id) for e in saved} == {
        (physics, 27),
        (maths, 25),
    }
    assert await external.get_field_map.execute(admin) == saved

    again = await external.put_field_map.execute(admin, [FieldMapEntry(maths, 25)])
    assert [e.subject_id for e in again] == [maths]


async def test_unknown_subjects_are_refused_and_named(
    external: ExternalServices, admin: Actor, academic: FakeAcademicDirectory
) -> None:
    """LIB-12: a map to a subject that does not exist is a mistake."""
    physics = academic.add_subject(new_id(), "Physics")
    ghost = new_id()

    with pytest.raises(FieldMapInvalidError) as caught:
        await external.put_field_map.execute(
            admin, [FieldMapEntry(physics, 27), FieldMapEntry(ghost, 25)]
        )

    assert caught.value.params["subject_ids"] == [str(ghost)]
    assert await external.get_field_map.execute(admin) == []


async def test_only_administration_edits_the_map(
    external: ExternalServices, student: Actor, librarian: Actor
) -> None:
    """LIB-12: students and librarians are refused."""
    for actor in (student, librarian):
        with pytest.raises(ForbiddenError):
            await external.get_field_map.execute(actor)
        with pytest.raises(ForbiddenError):
            await external.put_field_map.execute(actor, [])
