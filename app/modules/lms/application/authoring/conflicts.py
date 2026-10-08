"""Building conflict errors that carry the current draft (LMS-13)."""

from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.domain.authoring.entities import Course, CourseStep
from app.modules.lms.domain.authoring.errors import DraftConflictError
from app.modules.lms.domain.authoring.permissions import CourseAccess
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork


async def course_conflict(
    presenter: Presenter,
    uow: AuthoringUnitOfWork,
    course: Course,
    access: CourseAccess,
) -> DraftConflictError:
    """Conflict whose `params.theirs` is the current `CourseDraft`."""
    view = await presenter.course_draft(uow, course, access)
    return DraftConflictError(params={"theirs": view.model_dump(mode="json")})


async def step_conflict(presenter: Presenter, step: CourseStep) -> DraftConflictError:
    """Conflict whose `params.theirs` is the current `StepDraft`."""
    view = await presenter.step_draft(step)
    return DraftConflictError(params={"theirs": view.model_dump(mode="json")})
