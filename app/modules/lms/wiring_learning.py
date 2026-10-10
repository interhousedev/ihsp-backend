"""Wiring of the learning side of the LMS (catalog, attempts, progress, review)."""

from dataclasses import dataclass

from app.modules.lms.application.learning.attempt_finisher import AttemptFinisher
from app.modules.lms.application.learning.course_page import CoursePageBuilder
from app.modules.lms.application.learning.enroll_in_course import EnrollInCourse
from app.modules.lms.application.learning.get_attempt import GetAttempt
from app.modules.lms.application.learning.get_course_page import GetCoursePage
from app.modules.lms.application.learning.get_step_view import GetStepView
from app.modules.lms.application.learning.get_video_stream import GetVideoStream
from app.modules.lms.application.learning.join_course import JoinCourse
from app.modules.lms.application.learning.list_broadcast_audience import (
    ListBroadcastAudience,
)
from app.modules.lms.application.learning.list_catalog import ListCatalog
from app.modules.lms.application.learning.list_course_students import (
    ListCourseStudents,
)
from app.modules.lms.application.learning.list_my_courses import ListMyCourses
from app.modules.lms.application.learning.mark_step_viewed import MarkStepViewed
from app.modules.lms.application.learning.next_card import NextCard
from app.modules.lms.application.learning.override_score import OverrideScore
from app.modules.lms.application.learning.review_card import ReviewCard
from app.modules.lms.application.learning.save_answers import SaveAnswers
from app.modules.lms.application.learning.source_reader import LmsSourceReaderImpl
from app.modules.lms.application.learning.start_attempt import StartAttempt
from app.modules.lms.application.learning.step_completion import StepCompletion
from app.modules.lms.application.learning.submit_attempt import SubmitAttempt
from app.modules.lms.domain.learning.live import RenderCache
from app.modules.lms.infrastructure.learning.daily_counters import RedisDailyCounters
from app.modules.lms.infrastructure.learning.uow import SqlLearningUnitOfWork
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.modules.lms.ports.preview_revisions import PreviewRevisions
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class LearningServices:
    """Use cases of the learning side (attribute name = use case file name)."""

    list_catalog: ListCatalog
    list_my_courses: ListMyCourses
    get_course_page: GetCoursePage
    enroll_in_course: EnrollInCourse
    join_course: JoinCourse
    get_step_view: GetStepView
    get_video_stream: GetVideoStream
    mark_step_viewed: MarkStepViewed
    start_attempt: StartAttempt
    save_answers: SaveAnswers
    submit_attempt: SubmitAttempt
    next_card: NextCard
    review_card: ReviewCard
    list_course_students: ListCourseStudents
    get_attempt: GetAttempt
    override_score: OverrideScore
    source_reader: LmsSourceReaderImpl
    list_broadcast_audience: ListBroadcastAudience


def build_learning(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    preview_revisions: PreviewRevisions,
    files: FilesApi | None = None,
) -> LearningServices:
    """Build the learning use cases.

    ``preview_revisions`` is the authoring side's `ensure_preview_revision`
    (I1 passes `container.lms.authoring.ensure_preview_revision`); ``files`` signs
    the URLs of uploaded videos.
    """

    def uow_factory() -> LearningUnitOfWork:
        return SqlLearningUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    clock = deps.clock
    cache = RenderCache()
    counters = RedisDailyCounters(deps.redis)
    completion = StepCompletion(cache)
    finisher = AttemptFinisher(completion)
    pages = CoursePageBuilder(identity, clock, cache)
    return LearningServices(
        list_catalog=ListCatalog(uow_factory),
        list_my_courses=ListMyCourses(uow_factory, clock),
        get_course_page=GetCoursePage(uow_factory, pages),
        enroll_in_course=EnrollInCourse(uow_factory, pages),
        join_course=JoinCourse(uow_factory, pages, deps.rate_limiter),
        get_step_view=GetStepView(uow_factory, clock, cache, finisher, counters),
        get_video_stream=GetVideoStream(uow_factory, cache, files),
        mark_step_viewed=MarkStepViewed(uow_factory, clock, cache),
        start_attempt=StartAttempt(uow_factory, clock, finisher, preview_revisions),
        save_answers=SaveAnswers(uow_factory, clock, finisher),
        submit_attempt=SubmitAttempt(uow_factory, clock, finisher),
        next_card=NextCard(uow_factory, clock, counters),
        review_card=ReviewCard(uow_factory, clock, counters),
        list_course_students=ListCourseStudents(uow_factory, clock, identity),
        get_attempt=GetAttempt(uow_factory, clock, identity, finisher),
        override_score=OverrideScore(uow_factory, clock, identity, completion),
        source_reader=LmsSourceReaderImpl(uow_factory),
        list_broadcast_audience=ListBroadcastAudience(uow_factory),
    )
