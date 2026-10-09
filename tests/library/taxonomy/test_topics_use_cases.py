"""LIB-4, LIB-2: reading and managing the topic tree."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.entities import Item, TopicLink
from app.modules.library.domain.errors import TopicNotFoundError
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import (
    NameRequiredError,
    SlugInvalidError,
    TopicParentInvalidError,
    TopicSlugTakenError,
    TopicSubjectFixedError,
    UnknownSubjectError,
)
from app.modules.library.domain.taxonomy_unset import UNSET
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.ids import new_id
from tests.factories.library import make_book
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.library.taxonomy.conftest import Recorded
from tests.library.taxonomy.helpers import item_entry, make_reading_list

import pytest

NAMES = {"uz": "Mexanika", "ru": "Механика", "en": "Mechanics"}


async def create(
    library: LibraryServices,
    actor: Actor,
    subject_id: UUID,
    *,
    name: dict[str, str] | None = None,
    parent_id: UUID | None = None,
    slug: str | None = None,
    year_of_study: int | None = None,
) -> UUID:
    view = await library.taxonomy.create_topic.execute(
        actor,
        subject_id=subject_id,
        name=name or NAMES,
        parent_id=parent_id,
        slug=slug,
        year_of_study=year_of_study,
    )
    return view.id


# - - - Reading - - -


async def test_anyone_reads_the_tree_in_their_own_language(
    library: LibraryServices, librarian: Actor, student: Actor, subject_id: UUID
) -> None:
    """LIB-4: names follow the profile language, else Accept-Language."""
    root = await create(library, librarian, subject_id)
    await create(
        library,
        librarian,
        subject_id,
        name={"uz": "Kinematika", "ru": "Кинематика", "en": "Kinematics"},
        parent_id=root,
    )

    anonymous = await library.taxonomy.list_topics.execute(
        None, subject_id=subject_id, accept_language="ru,en;q=0.5"
    )
    signed_in = await library.taxonomy.list_topics.execute(
        student, subject_id=subject_id
    )

    assert [t.name for t in anonymous] == ["Механика"]
    assert [c.name for c in anonymous[0].children] == ["Кинематика"]
    assert signed_in[0].name == "Mechanics"  # the fake profile language is English
    assert anonymous[0].slug == "mechanics"


async def test_tree_of_all_subjects_when_no_subject_is_given(
    library: LibraryServices,
    librarian: Actor,
    subject_id: UUID,
    academic: FakeAcademicDirectory,
) -> None:
    """LIB-4: without ?subject_id the roots of every subject come back."""
    other = academic.add_subject(new_id(), "Chemistry")
    await create(library, librarian, subject_id)
    await create(library, librarian, other, name={"en": "Acids"})

    tree = await library.taxonomy.list_topics.execute(None)

    assert {t.subject_id for t in tree} == {subject_id, other}


# - - - Creating - - -


async def test_librarian_creates_a_root_topic_with_a_generated_slug(
    library: LibraryServices,
    librarian: Actor,
    subject_id: UUID,
    recorded: Recorded,
) -> None:
    """LIB-4, LIB-2: slug from the English name; the action is audited."""
    view = await library.taxonomy.create_topic.execute(
        librarian,
        subject_id=subject_id,
        name=NAMES,
        parent_id=None,
        slug=None,
        year_of_study=1,
    )

    assert (view.slug, view.position, view.year_of_study) == ("mechanics", 0, 1)
    assert view.name == NAMES
    (event,) = recorded.audits
    assert event.type == TaxonomyAuditType.TOPIC_CREATE
    assert event.actor_id == librarian.user_id
    assert event.metadata is not None and event.metadata["topic_id"] == str(view.id)


async def test_siblings_with_the_same_name_get_numbered_slugs_and_positions(
    library: LibraryServices, librarian: Actor, subject_id: UUID
) -> None:
    """LIB-4: the second 'Mechanics' becomes mechanics-2, placed after the first."""
    await create(library, librarian, subject_id)
    second = await library.taxonomy.create_topic.execute(
        librarian,
        subject_id=subject_id,
        name=NAMES,
        parent_id=None,
        slug=None,
        year_of_study=None,
    )

    assert (second.slug, second.position) == ("mechanics-2", 1)


async def test_explicit_slug_taken_by_a_sibling_is_a_conflict(
    library: LibraryServices, librarian: Actor, subject_id: UUID
) -> None:
    """LIB-4: library/topic-slug-taken (409) for a chosen slug."""
    await create(library, librarian, subject_id, slug="optics")

    with pytest.raises(TopicSlugTakenError):
        await create(library, librarian, subject_id, slug="optics")
    with pytest.raises(SlugInvalidError):
        await create(library, librarian, subject_id, slug="Not A Slug")


async def test_children_may_reuse_a_slug_under_another_parent(
    library: LibraryServices, librarian: Actor, subject_id: UUID
) -> None:
    """LIB-4: slugs are unique per (subject, parent)."""
    one = await create(library, librarian, subject_id, name={"en": "One"})
    two = await create(library, librarian, subject_id, name={"en": "Two"})

    a = await create(library, librarian, subject_id, parent_id=one, slug="intro")
    b = await create(library, librarian, subject_id, parent_id=two, slug="intro")

    assert a != b


async def test_parent_must_exist_in_the_same_subject(
    library: LibraryServices,
    librarian: Actor,
    subject_id: UUID,
    academic: FakeAcademicDirectory,
) -> None:
    """LIB-4: library/topic-parent-invalid."""
    other = academic.add_subject(new_id(), "Chemistry")
    foreign = await create(library, librarian, other)

    with pytest.raises(TopicParentInvalidError):
        await create(library, librarian, subject_id, parent_id=foreign)
    with pytest.raises(TopicParentInvalidError):
        await create(library, librarian, subject_id, parent_id=new_id())


async def test_unknown_subject_and_empty_names_are_refused(
    library: LibraryServices, librarian: Actor, subject_id: UUID
) -> None:
    """LIB-4: subject ids are validated through the academic directory."""
    with pytest.raises(UnknownSubjectError):
        await create(library, librarian, new_id())
    with pytest.raises(NameRequiredError):
        await create(library, librarian, subject_id, name={"uz": " "})


async def test_only_librarians_and_admins_manage_topics(
    library: LibraryServices,
    student: Actor,
    teacher: Actor,
    admin: Actor,
    subject_id: UUID,
) -> None:
    """LIB-2: students and teachers cannot touch the taxonomy."""
    for actor in (student, teacher):
        with pytest.raises(ForbiddenError):
            await create(library, actor, subject_id)
        with pytest.raises(ForbiddenError):
            await library.taxonomy.list_manage_topics.execute(actor)

    await create(library, admin, subject_id)
    assert len(await library.taxonomy.list_manage_topics.execute(admin)) == 1


# - - - Updating - - -


async def test_topic_is_renamed_and_its_year_cleared(
    library: LibraryServices, librarian: Actor, subject_id: UUID, recorded: Recorded
) -> None:
    """LIB-4: PATCH changes only what was sent; null clears the year."""
    topic = await create(library, librarian, subject_id, year_of_study=2)

    renamed = await library.taxonomy.update_topic.execute(
        librarian,
        topic,
        name={"uz": "Optika", "ru": "Оптика", "en": "Optics"},
    )
    cleared = await library.taxonomy.update_topic.execute(
        librarian, topic, year_of_study=None
    )

    assert renamed.name["en"] == "Optics"
    assert renamed.year_of_study == 2
    assert renamed.slug == "mechanics"  # a rename keeps the URL
    assert cleared.year_of_study is None
    assert cleared.name["en"] == "Optics"
    assert [e.type for e in recorded.audits][-1] == TaxonomyAuditType.TOPIC_UPDATE


async def test_slug_change_checks_siblings(
    library: LibraryServices, librarian: Actor, subject_id: UUID
) -> None:
    """LIB-4: a new slug may not collide; keeping the own slug is fine."""
    first = await create(library, librarian, subject_id, slug="optics")
    await create(library, librarian, subject_id, name={"en": "Waves"}, slug="waves")

    with pytest.raises(TopicSlugTakenError):
        await library.taxonomy.update_topic.execute(librarian, first, slug="waves")
    same = await library.taxonomy.update_topic.execute(librarian, first, slug="optics")

    assert same.slug == "optics"


async def test_topic_moves_under_another_and_back_to_the_root(
    library: LibraryServices, librarian: Actor, subject_id: UUID
) -> None:
    """LIB-4: parent_id changes the place; null makes the topic a root again."""
    root = await create(library, librarian, subject_id, name={"en": "Root"})
    leaf = await create(library, librarian, subject_id, name={"en": "Leaf"})

    moved = await library.taxonomy.update_topic.execute(librarian, leaf, parent_id=root)
    back = await library.taxonomy.update_topic.execute(librarian, leaf, parent_id=None)

    assert moved.parent_id == root
    assert back.parent_id is None


async def test_move_that_would_loop_or_cross_subjects_is_refused(
    library: LibraryServices, librarian: Actor, subject_id: UUID
) -> None:
    """LIB-4: no cycles; a topic stays in its subject."""
    root = await create(library, librarian, subject_id, name={"en": "Root"})
    child = await create(
        library, librarian, subject_id, name={"en": "Child"}, parent_id=root
    )

    with pytest.raises(TopicParentInvalidError):
        await library.taxonomy.update_topic.execute(librarian, root, parent_id=child)
    with pytest.raises(TopicParentInvalidError):
        await library.taxonomy.update_topic.execute(librarian, root, parent_id=root)
    with pytest.raises(TopicSubjectFixedError):
        await library.taxonomy.update_topic.execute(
            librarian, root, subject_id=new_id()
        )
    unchanged = await library.taxonomy.update_topic.execute(
        librarian, root, subject_id=subject_id, name=UNSET
    )
    assert unchanged.subject_id == subject_id


async def test_update_of_a_missing_topic_is_a_not_found(
    library: LibraryServices, librarian: Actor
) -> None:
    """LIB-4: library/topic-not-found."""
    with pytest.raises(TopicNotFoundError):
        await library.taxonomy.update_topic.execute(librarian, new_id(), slug="x")


# - - - Deleting - - -


async def test_delete_removes_the_subtree_and_counts_the_item_links(
    library: LibraryServices,
    librarian: Actor,
    teacher: Actor,
    subject_id: UUID,
    uow_factory: UowFactory,
    store_item: Callable[[Item], Awaitable[Item]],
    recorded: Recorded,
) -> None:
    """LIB-4: the links of items go with the topic; the audit event has the count."""
    root = await create(library, librarian, subject_id, name={"en": "Root"})
    child = await create(
        library, librarian, subject_id, name={"en": "Child"}, parent_id=root
    )
    keep = await create(library, librarian, subject_id, name={"en": "Keep"})
    book = await store_item(make_book())
    reading_list = make_reading_list(teacher.user_id, subject_id=subject_id)
    async with uow_factory() as uow:
        await uow.items.set_topic_links(
            book.id, [TopicLink(root), TopicLink(child, 3, 9), TopicLink(keep)]
        )
        await uow.lists.add(reading_list)
        await uow.lists.replace_entries(
            reading_list.id, [item_entry(0, book.id, topic_id=child)]
        )
        await uow.commit()

    await library.taxonomy.delete_topic.execute(librarian, root)

    async with uow_factory() as uow:
        left = await uow.taxonomy.topics(subject_id)
        links = await uow.items.topic_links([book.id])
        entries = await uow.lists.entries([reading_list.id])
    assert [t.id for t in left] == [keep]
    assert [link.topic_id for link in links[book.id]] == [keep]
    assert entries[reading_list.id][0].topic_id is None
    event = recorded.audits[-1]
    assert event.type == TaxonomyAuditType.TOPIC_DELETE
    assert event.metadata is not None
    assert event.metadata["item_links_removed"] == 2
    assert event.metadata["topics_removed"] == 2


async def test_deleting_a_missing_topic_is_a_not_found(
    library: LibraryServices, librarian: Actor
) -> None:
    """LIB-4: library/topic-not-found."""
    with pytest.raises(TopicNotFoundError):
        await library.taxonomy.delete_topic.execute(librarian, new_id())
