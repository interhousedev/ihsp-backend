"""LIB-5, LIB-12: the filter lists of the UniLibrary search."""

from app.modules.library.domain.errors import (
    ExternalDisabledError,
    ExternalUnavailableError,
)
from app.modules.library.ports.external_catalog import ExternalTaxonomies
from app.modules.library.wiring_external import ExternalServices
from app.shared.actor import Actor
from tests.fakes.library.external_catalog import FakeExternalCatalog
from tests.fakes.library.identity import FakeLibraryIdentity

import pytest


async def test_taxonomies_list_types_fields_languages_and_access(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-5: `{types, fields, languages, access}`."""
    view = await external.get_taxonomies.execute(student)

    assert [(t.id, t.name) for t in view.types] == [(9, "Darslik"), (2, "Qo'llanma")]
    assert [f.id for f in view.fields] == [27, 25]
    assert [(x.id, x.name) for x in view.languages] == [(2, "O'zbek"), (26, "Lotin")]
    assert catalog.taxonomy_calls == ["en"]


async def test_access_options_are_ours_and_translated(
    external: ExternalServices, student: Actor
) -> None:
    """LIB-5: any, open, partial, closed, named in the user's language."""
    view = await external.get_taxonomies.execute(student)

    assert [a.id for a in view.access] == ["any", "open", "partial", "closed"]
    assert [a.name for a in view.access] == [
        "Any access",
        "Fully open",
        "Partly open",
        "By request",
    ]


async def test_names_follow_the_language_of_the_profile(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    identity: FakeLibraryIdentity,
    other_student: Actor,
) -> None:
    """LIB-5: a Russian profile gets Russian names, also from UniLibrary."""
    identity.add(other_student, first="Bobur", last="Aliyev", locale="ru")

    view = await external.get_taxonomies.execute(other_student)

    assert view.access[1].name == "Полностью открыт"
    assert catalog.taxonomy_calls == ["ru"]


async def test_taxonomies_work_while_the_source_is_stale(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: the catalogue marks stale ones; the user still gets the lists."""
    catalog.taxonomy_value = ExternalTaxonomies(stale=True)

    view = await external.get_taxonomies.execute(student)

    assert view.types == ()
    assert len(view.access) == 4


async def test_taxonomies_are_unavailable_without_cache_and_source(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: nothing cached and the source is down."""
    catalog.unavailable()

    with pytest.raises(ExternalUnavailableError):
        await external.get_taxonomies.execute(student)


async def test_switched_off_answers_not_found(
    external_off: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: flag off."""
    with pytest.raises(ExternalDisabledError):
        await external_off.get_taxonomies.execute(student)

    assert catalog.calls == 0
