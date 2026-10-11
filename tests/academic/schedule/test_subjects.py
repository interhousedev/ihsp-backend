"""Subjects (ADM-7)."""

from app.modules.academic.domain.schedule.errors import (
    SubjectEmisIdTakenError,
    SubjectNameInvalidError,
    SubjectNotFoundError,
)
from app.modules.academic.domain.schedule.subject import Subject, subject_name
from app.shared.ids import new_id
from tests.academic.schedule.env import Env

import pytest


def make_subject(**names: str) -> Subject:
    """A subject with the given names (uz, ru, en)."""
    return Subject(id=new_id(), name=names, short_name="S")


def test_the_name_falls_back_from_the_locale_to_uz_ru_en() -> None:
    """ADM-7: EMIS often leaves one language empty."""
    only_ru = make_subject(uz="", ru="Математика", en="")
    both = make_subject(uz="Matematika", ru="Математика", en="Mathematics")
    only_en = make_subject(uz=" ", ru="", en="Mathematics")

    assert subject_name(only_ru, "uz") == "Математика"
    assert subject_name(both, "en") == "Mathematics"
    assert subject_name(both, "ru") == "Математика"
    assert subject_name(only_en, "uz") == "Mathematics"


def test_a_subject_without_any_name_falls_back_to_the_short_name() -> None:
    """ADM-7: never return an empty label if something is known."""
    assert (
        subject_name(Subject(id=new_id(), name={}, short_name="Math"), "ru") == "Math"
    )


async def test_a_subject_is_created_with_names_in_three_languages(env: Env) -> None:
    """ADM-7: add a subject that is not in EMIS."""
    created = await env.services.create_subject.execute(
        name={"uz": "Matematika", "ru": "Математика", "en": "Mathematics"},
        short_name="Math",
        can_be_divided=True,
    )

    assert created.name["ru"] == "Математика"
    assert created.emis_subject_id is None and created.can_be_divided is True


async def test_a_subject_needs_a_name(env: Env) -> None:
    """ADM-7: at least one language is required."""
    with pytest.raises(SubjectNameInvalidError):
        await env.services.create_subject.execute(name={"uz": " ", "ru": "", "en": ""})


async def test_an_emis_subject_can_be_linked_once(env: Env) -> None:
    """spec -> Subject: emis_subject_id is unique."""
    await env.services.create_subject.execute(name={"ru": "Физика"}, emis_subject_id=77)

    with pytest.raises(SubjectEmisIdTakenError):
        await env.services.create_subject.execute(
            name={"ru": "Химия"}, emis_subject_id=77
        )


async def test_a_subject_is_linked_to_emis_by_update(env: Env) -> None:
    """ADM-7: link a subject to its EMIS subject."""
    subject = await env.services.create_subject.execute(name={"ru": "Физика"})

    linked = await env.services.update_subject.execute(subject.id, emis_subject_id=77)
    cleared = await env.services.update_subject.execute(
        subject.id, emis_subject_id=None
    )

    assert linked.emis_subject_id == 77
    assert cleared.emis_subject_id is None


async def test_linking_to_a_taken_emis_subject_is_refused(env: Env) -> None:
    """ADM-7: the link is exclusive."""
    await env.services.create_subject.execute(name={"ru": "Физика"}, emis_subject_id=77)
    other = await env.services.create_subject.execute(name={"ru": "Химия"})

    with pytest.raises(SubjectEmisIdTakenError):
        await env.services.update_subject.execute(other.id, emis_subject_id=77)


async def test_updating_keeps_fields_that_were_not_sent(env: Env) -> None:
    """API: PATCH changes only the sent fields."""
    subject = await env.services.create_subject.execute(
        name={"ru": "Физика"}, short_name="Физ", can_be_divided=True
    )

    renamed = await env.services.update_subject.execute(
        subject.id, name={"ru": "Физика 2", "uz": "", "en": ""}
    )

    assert renamed.name["ru"] == "Физика 2"
    assert (renamed.short_name, renamed.can_be_divided) == ("Физ", True)


async def test_updating_an_unknown_subject_is_not_found(env: Env) -> None:
    """API: unknown ids answer 404."""
    with pytest.raises(SubjectNotFoundError):
        await env.services.update_subject.execute(new_id(), can_be_divided=True)


async def test_subjects_can_be_searched_by_any_name(env: Env) -> None:
    """ADM-7: ?query matches names in every language and the short name."""
    await env.services.create_subject.execute(
        name={"uz": "Fizika", "ru": "Физика", "en": "Physics"}
    )
    await env.services.create_subject.execute(name={"ru": "Химия"}, short_name="Хим")

    by_ru = await env.services.list_subjects.execute("Физ")
    by_uz = await env.services.list_subjects.execute("fizi")
    by_short = await env.services.list_subjects.execute("Хим")
    everything = await env.services.list_subjects.execute(None)

    assert [s.name["ru"] for s in by_ru] == ["Физика"]
    assert len(by_uz) == 1 and len(by_short) == 1
    assert len(everything) == 2


async def test_search_treats_wildcards_as_text(env: Env) -> None:
    """Search input is not a LIKE pattern."""
    await env.services.create_subject.execute(name={"ru": "Физика"})

    assert await env.services.list_subjects.execute("%") == []
