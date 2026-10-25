"""Mapping of topics to the read models."""

from collections.abc import Sequence

from app.modules.library.application.cards import pick_name
from app.modules.library.application.taxonomy.views import ManageTopicView, TopicView
from app.modules.library.domain.taxonomy_topics import Topic, TopicNode


def manage_topic_view(topic: Topic) -> ManageTopicView:
    """A topic with all three names."""
    return ManageTopicView(
        id=topic.id,
        subject_id=topic.subject_id,
        parent_id=topic.parent_id,
        name=dict(topic.name),
        slug=topic.slug,
        position=topic.position,
        year_of_study=topic.year_of_study,
        code=topic.code,
        archived=topic.archived,
    )


def topic_views(nodes: Sequence[TopicNode], locale: str) -> list[TopicView]:
    """The tree with each name in the reader's language."""
    return [
        TopicView(
            id=node.topic.id,
            subject_id=node.topic.subject_id,
            name=pick_name(node.topic.name, locale),
            slug=node.topic.slug,
            year_of_study=node.topic.year_of_study,
            children=tuple(topic_views(node.children, locale)),
        )
        for node in nodes
    ]
