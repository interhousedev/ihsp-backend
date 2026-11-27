"""Fills `academic.curriculum_topics` from the topics of the subject's lessons.

EMIS exposes no thematic plan, only the topic a teacher entered per class
(`lessons.emis_topic`); the plan is therefore derived from those topics, in the
order the lessons were held. Existing rows stay (a topic never disappears from
the bank's catalogue), new ones are appended after them.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_REFRESH = text("""
    INSERT INTO academic.curriculum_topics (emis_subject_id, semester, topic, position)
    SELECT s.emis_subject_id,
           t.half,
           left(btrim(l.emis_topic), 255),
           (coalesce(
               (SELECT max(c.position) FROM academic.curriculum_topics c
                 WHERE c.emis_subject_id = s.emis_subject_id), -1)
            + dense_rank() OVER (
                PARTITION BY s.emis_subject_id
                ORDER BY min(l.date) OVER (
                    PARTITION BY s.emis_subject_id, t.half,
                                 left(btrim(l.emis_topic), 255)),
                         left(btrim(l.emis_topic), 255)))::int
    FROM academic.lessons l
    JOIN academic.subjects s ON s.id = l.subject_id
    JOIN academic.terms t ON t.id = l.term_id
    WHERE s.emis_subject_id IS NOT NULL
      AND l.emis_topic IS NOT NULL AND btrim(l.emis_topic) <> ''
    ON CONFLICT DO NOTHING
    """)


class RefreshCurriculumTopics:
    """Adds the lesson topics of every EMIS subject to its topic directory."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self.sessionmaker = sessionmaker

    async def execute(self) -> int:
        """Insert the missing topics; return how many were added."""
        async with self.sessionmaker() as session, session.begin():
            result = await session.execute(_REFRESH)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
