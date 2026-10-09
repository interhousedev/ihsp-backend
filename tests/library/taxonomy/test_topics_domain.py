"""LIB-4: topics are a tree per subject; names, slugs and moves follow the rules."""

from datetime import UTC, datetime
from uuid import UUID

from app.modules.library.domain.taxonomy_errors import (
    NameRequiredError,
    SlugInvalidError,
    TopicParentInvalidError,
)
from app.modules.library.domain.taxonomy_topics import (
    Topic,
    build_tree,
    check_parent,
    clean_names,
    descendant_ids,
    slug_from_names,
    unique_slug,
    validate_slug,
)
from app.shared.ids import new_id

import pytest

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
SUBJECT = new_id()


def topic(
    name: str = "Mechanics",
    *,
    parent: UUID | None = None,
    position: int = 0,
    subject: UUID = SUBJECT,
) -> Topic:
    return Topic(
        id=new_id(),
        subject_id=subject,
        parent_id=parent,
        name={"uz": name, "ru": name, "en": name},
        slug=name.lower(),
        position=position,
        year_of_study=None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_names_are_trimmed_and_missing_languages_become_empty() -> None:
    """LIB-4: all three languages are stored; extra spaces are removed."""
    cleaned = clean_names({"uz": "  Kinematika ", "ru": "Кинематика  ва  т.д."})

    assert cleaned == {"uz": "Kinematika", "ru": "Кинематика ва т.д.", "en": ""}


def test_a_topic_without_any_name_is_refused() -> None:
    """LIB-4: at least one language must carry a name."""
    with pytest.raises(NameRequiredError):
        clean_names({"uz": " ", "ru": "", "en": ""})


def test_slug_comes_from_english_then_russian_then_uzbek() -> None:
    """LIB-4: the readable part of the URL prefers English."""
    assert slug_from_names({"uz": "Mexanika", "ru": "Механика", "en": "Mechanics"}) == (
        "mechanics"
    )
    assert slug_from_names({"uz": "Optika", "ru": "Механика", "en": ""}) == "mexanika"
    assert slug_from_names({"uz": "Optika", "ru": "", "en": ""}) == "optika"


def test_slug_of_a_name_without_letters_falls_back_to_topic() -> None:
    """LIB-4: punctuation only still gives a usable slug."""
    assert slug_from_names({"uz": "???", "ru": "", "en": ""}) == "topic"


def test_taken_slug_gets_the_next_free_number() -> None:
    """LIB-4: two siblings never share a slug."""
    assert unique_slug("optics", set()) == "optics"
    assert unique_slug("optics", {"optics"}) == "optics-2"
    assert unique_slug("optics", {"optics", "optics-2"}) == "optics-3"


def test_explicit_slug_must_be_lowercase_words() -> None:
    """LIB-4: slugs are lowercase Latin words joined by hyphens."""
    assert validate_slug("wave-optics") == "wave-optics"
    for bad in ("Wave Optics", "-optics", "optics-", "oп", "a" * 81, ""):
        with pytest.raises(SlugInvalidError):
            validate_slug(bad)


def test_tree_nests_children_under_parents_in_position_order() -> None:
    """LIB-4: GET /library/topics answers a tree ordered by position."""
    root_b = topic("Beta", position=2)
    root_a = topic("Alpha", position=1)
    child_2 = topic("Child two", parent=root_a.id, position=2)
    child_1 = topic("Child one", parent=root_a.id, position=1)
    grandchild = topic("Grandchild", parent=child_1.id)

    tree = build_tree([root_b, child_2, grandchild, root_a, child_1])

    assert [node.topic.name["en"] for node in tree] == ["Alpha", "Beta"]
    assert [n.topic.name["en"] for n in tree[0].children] == ["Child one", "Child two"]
    assert tree[0].children[0].children[0].topic is grandchild
    assert tree[1].children == ()


def test_descendants_cover_the_whole_subtree_but_not_the_topic_itself() -> None:
    """LIB-4: deleting a topic also removes what hangs under it."""
    root = topic("Root")
    child = topic("Child", parent=root.id)
    grandchild = topic("Grandchild", parent=child.id)
    other = topic("Other")

    found = descendant_ids([root, child, grandchild, other], root.id)

    assert found == {child.id, grandchild.id}


def test_parent_must_belong_to_the_same_subject() -> None:
    """LIB-4: a topic cannot hang under a topic of another subject."""
    foreign = topic("Foreign", subject=new_id())

    with pytest.raises(TopicParentInvalidError):
        check_parent([foreign], subject_id=SUBJECT, parent_id=foreign.id)

    with pytest.raises(TopicParentInvalidError):
        check_parent([], subject_id=SUBJECT, parent_id=new_id())


def test_topic_cannot_move_under_itself_or_below_its_own_child() -> None:
    """LIB-4: moves never create a cycle."""
    root = topic("Root")
    child = topic("Child", parent=root.id)
    topics = [root, child]

    with pytest.raises(TopicParentInvalidError):
        check_parent(topics, subject_id=SUBJECT, parent_id=root.id, topic_id=root.id)
    with pytest.raises(TopicParentInvalidError):
        check_parent(topics, subject_id=SUBJECT, parent_id=child.id, topic_id=root.id)
    check_parent(topics, subject_id=SUBJECT, parent_id=root.id, topic_id=child.id)
