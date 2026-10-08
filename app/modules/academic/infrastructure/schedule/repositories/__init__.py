"""SQL repositories of the academic schedule."""

from app.modules.academic.infrastructure.schedule.repositories.group_repository import (  # noqa: E501
    SqlGroupRepository,
)
from app.modules.academic.infrastructure.schedule.repositories.lesson_repository import (  # noqa: E501
    SqlLessonRepository,
)
from app.modules.academic.infrastructure.schedule.repositories.room_repository import (  # noqa: E501
    SqlRoomRepository,
)
from app.modules.academic.infrastructure.schedule.repositories.student_repository import (  # noqa: E501
    SqlStudentRepository,
)
from app.modules.academic.infrastructure.schedule.repositories.subject_repository import (  # noqa: E501
    SqlSubjectRepository,
)
from app.modules.academic.infrastructure.schedule.repositories.term_repository import (  # noqa: E501
    SqlTermRepository,
)
from app.modules.academic.infrastructure.schedule.repositories.timetable_entry_repository import (  # noqa: E501
    SqlTimetableEntryRepository,
)

__all__ = [
    "SqlGroupRepository",
    "SqlLessonRepository",
    "SqlRoomRepository",
    "SqlStudentRepository",
    "SqlSubjectRepository",
    "SqlTermRepository",
    "SqlTimetableEntryRepository",
]
