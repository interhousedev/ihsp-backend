"""Wiring of the learning side of the LMS (catalog, attempts, progress, review)."""

from dataclasses import dataclass

from app.modules.lms.application.h5p_links import H5PLinks
from app.modules.lms.application.html_widget_links import HtmlWidgetLinks
from app.modules.lms.application.learning.ai_review import AiReviews
from app.modules.lms.application.learning.answer_interaction import (
    AnswerInteraction,
)
from app.modules.lms.application.learning.attempt_finisher import AttemptFinisher
from app.modules.lms.application.learning.audience import (
    AudienceGate,
    StepLock,
    StudentGroupLookup,
)
from app.modules.lms.application.learning.course_page import CoursePageBuilder
from app.modules.lms.application.learning.enroll_in_course import EnrollInCourse
from app.modules.lms.application.learning.exam_answers import SaveExamAnswers
from app.modules.lms.application.learning.exam_get import GetExamSession
from app.modules.lms.application.learning.exam_start import StartExamModule
from app.modules.lms.application.learning.exam_submit import SubmitExamModule
from app.modules.lms.application.learning.get_attempt import GetAttempt
from app.modules.lms.application.learning.get_course_landing import GetCourseLanding
from app.modules.lms.application.learning.get_course_page import GetCoursePage
from app.modules.lms.application.learning.get_h5p_launch import GetH5PLaunch
from app.modules.lms.application.learning.get_hidden_tests import GetHiddenTests
from app.modules.lms.application.learning.get_html_widget_launch import (
    GetHtmlWidgetLaunch,
)
from app.modules.lms.application.learning.get_step_view import GetStepView
from app.modules.lms.application.learning.get_video_stream import (
    GetVideoCaptions,
    GetVideoStream,
)
from app.modules.lms.application.learning.issue_media_grant import IssueMediaGrant
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
from app.modules.lms.application.learning.public_courses import PublicCourses
from app.modules.lms.application.learning.read_step_for_mcp import LearnerCourseReader
from app.modules.lms.application.learning.record_h5p_result import RecordH5PResult
from app.modules.lms.application.learning.record_widget_result import (
    RecordWidgetResult,
)
from app.modules.lms.application.learning.redeem_media_grant import RedeemMediaGrant
from app.modules.lms.application.learning.review_card import ReviewCard
from app.modules.lms.application.learning.revoke_media_grants import RevokeMediaGrants
from app.modules.lms.application.learning.save_answers import SaveAnswers
from app.modules.lms.application.learning.source_reader import LmsSourceReaderImpl
from app.modules.lms.application.learning.start_attempt import StartAttempt
from app.modules.lms.application.learning.step_completion import StepCompletion
from app.modules.lms.application.learning.submit_attempt import SubmitAttempt
from app.modules.lms.domain.learning.live import RenderCache
from app.modules.lms.infrastructure.learning.ai_review_store import SqlAiReviewStore
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
    get_video_captions: GetVideoCaptions
    get_h5p_launch: GetH5PLaunch
    get_html_widget_launch: GetHtmlWidgetLaunch
    record_h5p_result: RecordH5PResult
    record_widget_result: RecordWidgetResult
    get_hidden_tests: GetHiddenTests
    exam_get: GetExamSession
    exam_start: StartExamModule
    exam_answers: SaveExamAnswers
    exam_submit: SubmitExamModule
    answer_interaction: AnswerInteraction
    h5p_links: H5PLinks
    html_widget_links: HtmlWidgetLinks
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
    get_course_landing: GetCourseLanding
    issue_media_grant: IssueMediaGrant
    redeem_media_grant: RedeemMediaGrant
    revoke_media_grants: RevokeMediaGrants
    learner_course_reader: LearnerCourseReader
    public_courses: PublicCourses
    ai_review: AiReviews | None


def build_learning(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    preview_revisions: PreviewRevisions,
    files: FilesApi | None = None,
    h5p_links: H5PLinks | None = None,
    widget_links: HtmlWidgetLinks | None = None,
    student_group: StudentGroupLookup | None = None,
    step_lock: StepLock | None = None,
) -> LearningServices:
    """Build the learning use cases.

    ``preview_revisions`` is the authoring side's `ensure_preview_revision`
    (I1 passes `container.lms.authoring.ensure_preview_revision`); ``files`` signs
    the URLs of uploaded videos; ``step_lock`` is the engagement mastery gate.
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
    gate = AudienceGate(identity, student_group)
    gate.step_lock = step_lock
    completion = StepCompletion(cache, gate)
    finisher = AttemptFinisher(completion)
    pages = CoursePageBuilder(identity, clock, cache, gate)
    links = h5p_links or H5PLinks(b"lms-h5p-test-key", clock, None)
    widgets = widget_links or HtmlWidgetLinks(b"lms-widget-test-key", clock, None)
    video_stream = GetVideoStream(uow_factory, cache, files, gate)
    return LearningServices(
        list_catalog=ListCatalog(uow_factory, gate),
        list_my_courses=ListMyCourses(uow_factory, clock, gate),
        get_course_page=GetCoursePage(uow_factory, pages),
        enroll_in_course=EnrollInCourse(uow_factory, pages, deps.kicker),
        join_course=JoinCourse(uow_factory, pages, deps.rate_limiter, deps.kicker),
        get_step_view=GetStepView(uow_factory, clock, cache, finisher, counters, gate),
        get_video_stream=video_stream,
        get_video_captions=GetVideoCaptions(video_stream),
        get_h5p_launch=GetH5PLaunch(uow_factory, cache, links, gate),
        get_html_widget_launch=GetHtmlWidgetLaunch(uow_factory, cache, widgets, gate),
        exam_get=GetExamSession(uow_factory, clock, completion, gate),
        exam_start=StartExamModule(uow_factory, clock, completion, gate),
        exam_answers=SaveExamAnswers(uow_factory, clock, completion, gate),
        exam_submit=SubmitExamModule(uow_factory, clock, completion, gate),
        record_h5p_result=RecordH5PResult(uow_factory, clock, completion, gate),
        record_widget_result=RecordWidgetResult(uow_factory, clock, completion, gate),
        get_hidden_tests=GetHiddenTests(uow_factory, gate),
        answer_interaction=AnswerInteraction(uow_factory, clock, completion, gate),
        h5p_links=links,
        html_widget_links=widgets,
        mark_step_viewed=MarkStepViewed(uow_factory, clock, cache, gate),
        start_attempt=StartAttempt(
            uow_factory, clock, finisher, preview_revisions, gate
        ),
        save_answers=SaveAnswers(uow_factory, clock, finisher),
        submit_attempt=SubmitAttempt(uow_factory, clock, finisher),
        next_card=NextCard(uow_factory, clock, counters, gate),
        review_card=ReviewCard(uow_factory, clock, counters, gate),
        list_course_students=ListCourseStudents(uow_factory, clock, identity, gate),
        get_attempt=GetAttempt(uow_factory, clock, identity, finisher),
        override_score=OverrideScore(uow_factory, clock, identity, completion),
        source_reader=LmsSourceReaderImpl(uow_factory, gate),
        list_broadcast_audience=ListBroadcastAudience(uow_factory),
        get_course_landing=GetCourseLanding(uow_factory, identity, clock, gate),
        issue_media_grant=IssueMediaGrant(uow_factory, clock, cache, gate),
        redeem_media_grant=RedeemMediaGrant(
            uow_factory, clock, cache, identity, files, deps.rate_limiter, gate
        ),
        revoke_media_grants=RevokeMediaGrants(uow_factory, clock),
        learner_course_reader=LearnerCourseReader(uow_factory, cache, gate),
        public_courses=PublicCourses(uow_factory, pages, cache, clock),
        ai_review=(
            AiReviews(
                uow_factory=uow_factory,
                gate=gate,
                store=SqlAiReviewStore(deps.sessionmaker),
                files=files,
                identity=identity,
                source_reader=LmsSourceReaderImpl(uow_factory, gate),
                model=None,
                web=None,
                limits=deps.effective_limits,
                rate_limiter=deps.rate_limiter,
                completion=completion,
            )
            if files is not None
            else None
        ),
    )
