"""In-memory `QuestionBankStore`."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.notebooks.domain.question_bank import BankQuestion
from app.shared.actor import Actor, Role


class FakeQuestionBankStore:
    """Questions in a dict, newest last."""

    def __init__(self) -> None:
        self.rows: dict[UUID, BankQuestion] = {}
        self.batches: list[int] = []

    async def add(self, question: BankQuestion) -> None:
        self.rows[question.id] = question

    async def get(self, question_id: UUID) -> BankQuestion | None:
        return self.rows.get(question_id)

    async def replace(self, question: BankQuestion) -> None:
        self.rows[question.id] = question

    async def delete(self, question_id: UUID) -> None:
        self.rows.pop(question_id, None)

    async def add_many(self, questions: Sequence[BankQuestion]) -> None:
        self.batches.append(len(questions))
        for q in questions:
            self.rows[q.id] = q

    def _seen(self, emis: int, viewer: UUID | None) -> list[BankQuestion]:
        return [
            q
            for q in self.rows.values()
            if q.emis_subject_id == emis
            and (viewer is None or q.owner_id == viewer or q.visibility == "subject")
        ]

    async def visible_texts(
        self, emis_subject_id: int, topic: str, viewer_id: UUID
    ) -> list[tuple[UUID, str]]:
        return [
            (q.id, q.question)
            for q in self._seen(emis_subject_id, viewer_id)
            if q.topic == topic
        ]

    async def visible_ids(
        self,
        emis_subject_id: int,
        topic: str,
        viewer_id: UUID,
        difficulty: str | None,
    ) -> list[UUID]:
        pool = [
            q
            for q in self._seen(emis_subject_id, viewer_id)
            if q.topic == topic and difficulty in (None, q.difficulty)
        ]
        pool.sort(key=lambda q: (q.created_at, str(q.id)))
        return [q.id for q in pool]

    async def get_many(self, ids: Sequence[UUID]) -> list[BankQuestion]:
        return [self.rows[i] for i in ids if i in self.rows]

    async def count_by_topic(
        self, emis_subject_id: int, viewer_id: UUID
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for q in self._seen(emis_subject_id, viewer_id):
            counts[q.topic] = counts.get(q.topic, 0) + 1
        return counts

    async def page(
        self,
        emis_subject_id: int,
        topic: str | None,
        viewer_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BankQuestion], int]:
        rows = [
            q
            for q in self._seen(emis_subject_id, viewer_id)
            if topic in (None, q.topic)
        ]
        rows.sort(key=lambda q: (q.created_at, str(q.id)), reverse=True)
        return rows[offset : offset + limit], len(rows)


class FakeSubjectTeaching:
    """`SubjectTeaching`: admins pass, teachers only for the EMIS ids given."""

    def __init__(self, taught: dict[UUID, set[int]] | None = None) -> None:
        """`None` lets every actor through; otherwise teacher id -> EMIS ids."""
        self.taught = taught

    async def teaches(self, actor: Actor, emis_subject_id: int) -> bool:
        """True for admins, and for the teachers listed in `taught`."""
        if self.taught is None or actor.has(Role.ADMIN):
            return True
        return emis_subject_id in self.taught.get(actor.user_id, set())


class FakeTopicCatalog:
    """`SubjectTopicCatalog`: EMIS subject -> the topics of its curriculum.

    The real one reads the academic topic directory (see spec 3.2a): a table
    `curriculum_topics(emis_subject_id, semester, topic)` filled from the EMIS
    thematic plan; a local subject without an EMIS id has no bank.
    """

    def __init__(self, topics: dict[int, tuple[str, ...]]) -> None:
        self.topics_by_subject = topics

    async def topics(self, emis_subject_id: int) -> tuple[str, ...] | None:
        """The subject's topics, or None when the EMIS subject is unknown."""
        return self.topics_by_subject.get(emis_subject_id)
