"""The assessments unit of work over one SQLAlchemy session."""

from app.modules.academic.infrastructure.assessments.repositories import (
    assessment_reader,
    assessment_repository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlAssessmentsUnitOfWork(SqlUnitOfWork):
    """One transaction with the assessment repositories bound to its session."""

    assessments: assessment_repository.SqlAssessmentRepository
    reader: assessment_reader.SqlAssessmentReader

    def _init_repos(self) -> None:
        """Create the repositories bound to the open session."""
        self.assessments = assessment_repository.SqlAssessmentRepository(self.session)
        self.reader = assessment_reader.SqlAssessmentReader(self.session)
