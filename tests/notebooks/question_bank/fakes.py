"""In-memory `QuestionBankStore`."""

from uuid import UUID

from app.modules.notebooks.domain.question_bank import BankQuestion


class FakeQuestionBankStore:
    """Questions in a dict, newest last."""

    def __init__(self) -> None:
        self.rows: dict[UUID, BankQuestion] = {}

    async def add(self, question: BankQuestion) -> None:
        self.rows[question.id] = question

    async def get(self, question_id: UUID) -> BankQuestion | None:
        return self.rows.get(question_id)

    async def replace(self, question: BankQuestion) -> None:
        self.rows[question.id] = question

    async def delete(self, question_id: UUID) -> None:
        self.rows.pop(question_id, None)

    async def list(self, emis_subject_id: int, topic: str | None) -> list[BankQuestion]:
        return [
            q
            for q in self.rows.values()
            if q.emis_subject_id == emis_subject_id and topic in (None, q.topic)
        ]


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
