"""Subjects as a librarian-managed tree: create, nest, reorder, archive, delete."""

from uuid import UUID

from app.modules.library.domain.entities import SubjectLink
from app.modules.library.domain.enums import SubjectRole
from app.modules.library.domain.errors import SubjectNotFoundError
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import (
    NameRequiredError,
    SubjectInUseError,
    SubjectParentInvalidError,
    SubjectSlugTakenError,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from tests.factories.library import make_book
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.library.taxonomy.conftest import Recorded

import pytest

NAMES = {"en": "Anything"}
ECONOMICS = {"uz": "Iqtisodiyot", "ru": "Экономика", "en": "Economics"}
SOCIAL = {"uz": "Ijtimoiy fanlar", "ru": "Социальные науки", "en": "Social Sciences"}


async def create(
    library: LibraryServices,
    actor: Actor,
    names: dict[str, str],
    *,
    parent_id: UUID | None = None,
    code: str | None = None,
    slug: str | None = None,
) -> UUID:
    view = await library.taxonomy.create_subject.execute(
        actor, name=names, parent_id=parent_id, code=code, slug=slug
    )
    return view.id


async def test_librarian_builds_a_tree_with_codes_and_positions(
    library: LibraryServices, librarian: Actor, recorded: Recorded
) -> None:
    """Subjects nest, keep a ББК/УДК code and take the last place among siblings."""
    social = await create(library, librarian, SOCIAL, code="  ББК 60 ·   УДК 3 ")
    economics = await create(library, librarian, ECONOMICS, code="ББК 65")
    history = await create(
        library,
        librarian,
        {"ru": "История"},
        parent_id=social,
        slug="history",
    )

    subjects = {
        s.id: s for s in await library.taxonomy.list_manage_subjects.execute(librarian)
    }

    assert subjects[social].code == "ББК 60 · УДК 3"
    assert subjects[social].slug == "social-sciences"
    assert (subjects[social].position, subjects[economics].position) == (0, 1)
    assert subjects[history].parent_id == social and subjects[history].position == 0
    assert subjects[history].name == {"uz": "", "ru": "История", "en": ""}
    assert TaxonomyAuditType.SUBJECT_CREATE.value in {a.type for a in recorded.audits}


async def test_a_name_in_some_language_is_required_and_slugs_are_unique(
    library: LibraryServices, librarian: Actor
) -> None:
    """An empty name is refused; a chosen slug that a sibling uses is a conflict."""
    with pytest.raises(NameRequiredError):
        await create(library, librarian, {"uz": " ", "ru": "", "en": ""})
    await create(library, librarian, ECONOMICS, slug="econ")

    with pytest.raises(SubjectSlugTakenError):
        await create(library, librarian, SOCIAL, slug="econ")
    # The slug of a name that is taken gets a number.
    again = await library.taxonomy.create_subject.execute(librarian, name=ECONOMICS)
    assert again.slug == "economics"
    other = await library.taxonomy.create_subject.execute(librarian, name=ECONOMICS)
    assert other.slug == "economics-2"


async def test_rename_recode_nest_reorder_and_archive(
    library: LibraryServices, librarian: Actor
) -> None:
    """PATCH changes only what is sent; nesting appends, `position` reorders."""
    a = await create(library, librarian, {"en": "A"})
    b = await create(library, librarian, {"en": "B"})
    c = await create(library, librarian, {"en": "C"})
    update = library.taxonomy.update_subject.execute

    renamed = await update(librarian, a, name={"uz": "", "ru": "Альфа", "en": "Alpha"})
    coded = await update(librarian, a, code="УДК 1")
    cleared = await update(librarian, a, code=None)
    moved = await update(librarian, c, position=0)
    nested = await update(librarian, b, parent_id=a)
    archived = await update(librarian, a, archived=True)
    restored = await update(librarian, a, archived=False)

    assert renamed.name["en"] == "Alpha" and renamed.slug == "a"
    assert coded.code == "УДК 1" and cleared.code is None
    assert moved.position == 0
    assert nested.parent_id == a and nested.position == 0
    assert archived.archived is True and restored.archived is False
    order = [
        s.id
        for s in await library.taxonomy.list_manage_subjects.execute(librarian)
        if s.parent_id is None
    ]
    assert order == [c, a]


async def test_a_subject_cannot_move_under_itself_or_its_child(
    library: LibraryServices, librarian: Actor
) -> None:
    """The tree stays acyclic."""
    root = await create(library, librarian, {"en": "Root"})
    child = await create(library, librarian, {"en": "Child"}, parent_id=root)

    with pytest.raises(SubjectParentInvalidError):
        await library.taxonomy.update_subject.execute(librarian, root, parent_id=root)
    with pytest.raises(SubjectParentInvalidError):
        await library.taxonomy.update_subject.execute(librarian, root, parent_id=child)
    with pytest.raises(SubjectParentInvalidError):
        await library.taxonomy.update_subject.execute(
            librarian, root, parent_id=UUID(int=1)
        )
    with pytest.raises(SubjectNotFoundError):
        await library.taxonomy.update_subject.execute(
            librarian, UUID(int=1), name=NAMES
        )


async def test_archived_subjects_leave_the_public_list_but_keep_their_books(
    library: LibraryServices, librarian: Actor, student: Actor
) -> None:
    """Archiving hides a subject from pickers; a book keeps the link and the name."""
    subject = await create(library, librarian, ECONOMICS)
    kept = await create(library, librarian, SOCIAL)

    before = await library.catalogue.list_subjects.execute(
        student, include_empty=True, accept_language="ru"
    )
    await library.taxonomy.update_subject.execute(librarian, subject, archived=True)
    after = await library.catalogue.list_subjects.execute(
        student, include_empty=True, accept_language="ru"
    )

    assert {v.id for v in before} == {subject, kept}
    assert {v.id for v in after} == {kept}
    assert next(v for v in before if v.id == subject).name in ECONOMICS.values()


async def test_delete_only_unused_subjects_without_children(
    library: LibraryServices, librarian: Actor, recorded: Recorded
) -> None:
    """A subject with sub-subjects or topics is archived, not deleted."""
    parent = await create(library, librarian, {"en": "Parent"})
    await create(library, librarian, {"en": "Child"}, parent_id=parent)
    topical = await create(library, librarian, {"en": "Topical"})
    await library.taxonomy.create_topic.execute(
        librarian, subject_id=topical, name={"en": "Topic"}
    )
    empty = await create(library, librarian, {"en": "Empty"})

    with pytest.raises(SubjectInUseError):
        await library.taxonomy.delete_subject.execute(librarian, parent)
    with pytest.raises(SubjectInUseError):
        await library.taxonomy.delete_subject.execute(librarian, topical)
    await library.taxonomy.delete_subject.execute(librarian, empty)

    ids = {s.id for s in await library.taxonomy.list_manage_subjects.execute(librarian)}
    assert empty not in ids and parent in ids
    assert TaxonomyAuditType.SUBJECT_DELETE.value in {a.type for a in recorded.audits}


async def test_a_book_in_a_subject_blocks_deleting_it(
    library: LibraryServices, librarian: Actor, uow_factory: UowFactory
) -> None:
    """Item links count as use."""
    subject = await create(library, librarian, ECONOMICS)
    book = make_book(title="Mikroiqtisodiyot")
    async with uow_factory() as uow:
        await uow.items.add(book)
        await uow.items.set_subject_links(
            book.id, [SubjectLink(subject, SubjectRole.TEXTBOOK)]
        )
        await uow.commit()

    with pytest.raises(SubjectInUseError) as caught:
        await library.taxonomy.delete_subject.execute(librarian, subject)
    assert caught.value.params["items"] == 1


async def test_only_librarians_manage_subjects(
    library: LibraryServices, student: Actor, teacher: Actor
) -> None:
    """Students and teachers cannot touch the tree."""
    for actor in (student, teacher):
        with pytest.raises(ForbiddenError):
            await library.taxonomy.list_manage_subjects.execute(actor)
        with pytest.raises(ForbiddenError):
            await create(library, actor, ECONOMICS)


async def test_library_subjects_resolve_as_subjects_and_old_ids_still_do(
    library: LibraryServices,
    librarian: Actor,
    academic: FakeAcademicDirectory,
    subject_id: UUID,
) -> None:
    """Reading lists and topics accept a library subject and a pre-tree academic id."""
    own = await create(library, librarian, ECONOMICS)

    new_topic = await library.taxonomy.create_topic.execute(
        librarian, subject_id=own, name={"en": "Money"}, code="ББК 65.012"
    )
    old_topic = await library.taxonomy.create_topic.execute(
        librarian, subject_id=subject_id, name={"en": "Mechanics"}
    )

    assert new_topic.code == "ББК 65.012" and new_topic.subject_id == own
    assert old_topic.subject_id == subject_id
    names = await library.core.academic.subject_names([own, subject_id], "ru")
    assert names[own] == "Экономика" and names[subject_id]
