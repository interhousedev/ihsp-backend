"""Labels a lesson carries from EMIS: its kind, and where its topic came from."""

from typing import Literal, get_args

LessonKind = Literal["lecture", "practice", "midterm", "final", "other"]
LESSON_KINDS: tuple[LessonKind, ...] = get_args(LessonKind)

# "emis": the topic is the one EMIS sent; "manual": a person wrote it.
TopicSource = Literal["emis", "manual"]


def topic_source_of(topic: str | None, emis_topic: str | None) -> TopicSource | None:
    """Say who the lesson's topic is from; None when it has no topic."""
    if topic is None:
        return None
    return "emis" if topic == emis_topic else "manual"
