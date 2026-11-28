"""Registers the renderers that the notify module owns."""

from app.modules.notify.application.renderers.account_closing import (
    AccountClosingRenderer,
)
from app.modules.notify.application.renderers.admission_affordability_signoff import (
    AdmissionAffordabilitySignoffRenderer,
)
from app.modules.notify.application.renderers.admission_comment_added import (
    AdmissionCommentAddedRenderer,
)
from app.modules.notify.application.renderers.admission_deadline_reminder import (
    AdmissionDeadlineReminderRenderer,
)
from app.modules.notify.application.renderers.admission_document_uploaded import (
    AdmissionDocumentUploadedRenderer,
)
from app.modules.notify.application.renderers.admission_help_requested import (
    AdmissionHelpRequestedRenderer,
)
from app.modules.notify.application.renderers.admission_help_responded import (
    AdmissionHelpRespondedRenderer,
)
from app.modules.notify.application.renderers.admission_review_ready import (
    AdmissionReviewReadyRenderer,
)
from app.modules.notify.application.renderers.assessment_reminder import (
    AssessmentReminderRenderer,
)
from app.modules.notify.application.renderers.broadcast import BroadcastRenderer
from app.modules.notify.application.renderers.chat_answer_ready import (
    ChatAnswerReadyRenderer,
)
from app.modules.notify.application.renderers.clubs import (
    ClubAnnouncementRenderer,
    ClubJoinRequestRenderer,
    ClubJoinResultRenderer,
    ClubOwnerGraduatingRenderer,
    ClubTransferOfferRenderer,
    DraftInviteRenderer,
    EventCancelledRenderer,
    EventChangedRenderer,
    EventRatingRequestRenderer,
    EventReminderRenderer,
    PositionApplicationResultRenderer,
)
from app.modules.notify.application.renderers.curator_absences import (
    CuratorAbsencesRenderer,
)
from app.modules.notify.application.renderers.curator_exam_mark import (
    CuratorExamMarkRenderer,
)
from app.modules.notify.application.renderers.deadline_changed import (
    DeadlineChangedRenderer,
)
from app.modules.notify.application.renderers.document_attached import (
    DocumentAttachedRenderer,
)
from app.modules.notify.application.renderers.document_rejected import (
    DocumentRejectedRenderer,
)
from app.modules.notify.application.renderers.emis_reauth import EmisReauthRenderer
from app.modules.notify.application.renderers.excuse_decided import (
    ExcuseDecidedRenderer,
)
from app.modules.notify.application.renderers.excuse_message import (
    ExcuseMessageRenderer,
)
from app.modules.notify.application.renderers.excuse_requested import (
    ExcuseRequestedRenderer,
)
from app.modules.notify.application.renderers.feedback_new import FeedbackNewRenderer
from app.modules.notify.application.renderers.files_expiring import (
    FilesExpiringRenderer,
)
from app.modules.notify.application.renderers.gate_unexcused_exit import (
    GateUnexcusedExitRenderer,
)
from app.modules.notify.application.renderers.homework_reviewed import (
    HomeworkReviewedRenderer,
)
from app.modules.notify.application.renderers.homework_submitted import (
    HomeworkSubmittedRenderer,
)
from app.modules.notify.application.renderers.knowledge_gap import KnowledgeGapRenderer
from app.modules.notify.application.renderers.lesson_absence import (
    LessonAbsenceRenderer,
)
from app.modules.notify.application.renderers.lesson_changed import (
    LessonChangedRenderer,
)
from app.modules.notify.application.renderers.lesson_resources import (
    LessonResourcesRenderer,
)
from app.modules.notify.application.renderers.library_item_approved import (
    LibraryItemApprovedRenderer,
)
from app.modules.notify.application.renderers.library_item_changes_requested import (
    LibraryItemChangesRequestedRenderer,
)
from app.modules.notify.application.renderers.library_item_rejected import (
    LibraryItemRejectedRenderer,
)
from app.modules.notify.application.renderers.library_item_unpublished import (
    LibraryItemUnpublishedRenderer,
)
from app.modules.notify.application.renderers.library_queue_waiting import (
    LibraryQueueWaitingRenderer,
)
from app.modules.notify.application.renderers.library_reading_list_new import (
    LibraryReadingListNewRenderer,
)
from app.modules.notify.application.renderers.library_report_filed import (
    LibraryReportFiledRenderer,
)
from app.modules.notify.application.renderers.library_suggestion_approved import (
    LibrarySuggestionApprovedRenderer,
)
from app.modules.notify.application.renderers.library_suggestion_declined import (
    LibrarySuggestionDeclinedRenderer,
)
from app.modules.notify.application.renderers.lms_nudges import (
    LmsDeadlineSoonRenderer,
    LmsReviewDueRenderer,
    LmsStreakAtRiskRenderer,
)
from app.modules.notify.application.renderers.login_failures import (
    LoginFailuresRenderer,
)
from app.modules.notify.application.renderers.mail_bounced import MailBouncedRenderer
from app.modules.notify.application.renderers.mail_suspended import (
    MailSuspendedRenderer,
)
from app.modules.notify.application.renderers.marks import MarksRenderer
from app.modules.notify.application.renderers.mcp_scope_offer import (
    McpScopeOfferRenderer,
)
from app.modules.notify.application.renderers.notebook_artifact_ready import (
    NotebookArtifactReadyRenderer,
)
from app.modules.notify.application.renderers.privacy_update import (
    PrivacyUpdateRenderer,
)
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.modules.notify.application.renderers.result_below import ResultBelowRenderer
from app.modules.notify.application.renderers.result_drop import ResultDropRenderer
from app.modules.notify.application.renderers.student_sync_failed import (
    StudentSyncFailedRenderer,
)
from app.modules.notify.application.renderers.sync_alert import SyncAlertRenderer
from app.modules.notify.application.renderers.teacher_temporary_marks import (
    TeacherTemporaryMarksRenderer,
)
from app.modules.notify.application.renderers.transcript_ready import (
    TranscriptReadyRenderer,
)
from app.modules.notify.application.renderers.transcript_reminder import (
    TranscriptReminderRenderer,
)
from app.modules.notify.application.renderers.transcript_requested import (
    TranscriptRequestedRenderer,
)
from app.modules.notify.application.renderers.transcript_scan_uploaded import (
    TranscriptScanUploadedRenderer,
)
from app.modules.notify.application.renderers.transcript_unrouted import (
    TranscriptUnroutedRenderer,
)
from app.settings import UrlsSettings
from app.shared.contracts.files import FilesApi
from app.shared.contracts.links import LinksApi
from app.shared.i18n.core import I18nCore
from app.shared.notifications import NotificationType


def register_builtin_renderers(
    registry: RendererRegistry,
    *,
    i18n: I18nCore,
    urls: UrlsSettings,
    links: LinksApi,
    files: FilesApi,
) -> None:
    """Add renderers for every type except those the bot module registers."""
    registry.register(NotificationType.MARKS, MarksRenderer(i18n, urls))
    registry.register(NotificationType.RESULT_DROP, ResultDropRenderer(i18n, urls))
    registry.register(NotificationType.RESULT_BELOW, ResultBelowRenderer(i18n, urls))
    registry.register(
        NotificationType.LESSON_RESOURCES, LessonResourcesRenderer(i18n, urls, links)
    )
    registry.register(
        NotificationType.LESSON_CHANGED, LessonChangedRenderer(i18n, urls)
    )
    registry.register(NotificationType.MAIL_BOUNCED, MailBouncedRenderer(i18n, urls))
    registry.register(NotificationType.BROADCAST, BroadcastRenderer(i18n, files))
    registry.register(NotificationType.EMIS_REAUTH, EmisReauthRenderer(i18n, urls))
    registry.register(
        NotificationType.FILES_EXPIRING, FilesExpiringRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.LOGIN_FAILURES, LoginFailuresRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.MCP_SCOPE_OFFER, McpScopeOfferRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.EXCUSE_REQUESTED, ExcuseRequestedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.EXCUSE_DECIDED, ExcuseDecidedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.EXCUSE_MESSAGE, ExcuseMessageRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.CHAT_ANSWER_READY, ChatAnswerReadyRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.TRANSCRIPT_REQUESTED, TranscriptRequestedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.TRANSCRIPT_REMINDER, TranscriptReminderRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.TRANSCRIPT_READY, TranscriptReadyRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.TRANSCRIPT_SCAN_UPLOADED,
        TranscriptScanUploadedRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.TRANSCRIPT_UNROUTED, TranscriptUnroutedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.ADMISSION_DOCUMENT_UPLOADED,
        AdmissionDocumentUploadedRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.DOCUMENT_ATTACHED, DocumentAttachedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.DOCUMENT_REJECTED, DocumentRejectedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.ADMISSION_DEADLINE_REMINDER,
        AdmissionDeadlineReminderRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.DEADLINE_CHANGED, DeadlineChangedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.ADMISSION_HELP_REQUESTED,
        AdmissionHelpRequestedRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.ADMISSION_HELP_RESPONDED,
        AdmissionHelpRespondedRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.ADMISSION_COMMENT_ADDED,
        AdmissionCommentAddedRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.ADMISSION_REVIEW_READY,
        AdmissionReviewReadyRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.ADMISSION_AFFORDABILITY_SIGNOFF,
        AdmissionAffordabilitySignoffRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.PRIVACY_UPDATE, PrivacyUpdateRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.ACCOUNT_CLOSING, AccountClosingRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.MAIL_SUSPENDED, MailSuspendedRenderer(i18n, urls)
    )
    registry.register(NotificationType.SYNC_ALERT, SyncAlertRenderer(i18n, urls))
    registry.register(
        NotificationType.STUDENT_SYNC_FAILED, StudentSyncFailedRenderer(i18n, urls)
    )
    registry.register(NotificationType.KNOWLEDGE_GAP, KnowledgeGapRenderer(i18n, urls))
    registry.register(
        NotificationType.GATE_UNEXCUSED_EXIT, GateUnexcusedExitRenderer(i18n, urls)
    )
    registry.register(NotificationType.FEEDBACK_NEW, FeedbackNewRenderer(i18n, urls))
    registry.register(
        NotificationType.NOTEBOOK_ARTIFACT_READY,
        NotebookArtifactReadyRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.ASSESSMENT_REMINDER, AssessmentReminderRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.LIBRARY_ITEM_APPROVED, LibraryItemApprovedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED,
        LibraryItemChangesRequestedRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.LIBRARY_ITEM_REJECTED, LibraryItemRejectedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.LIBRARY_ITEM_UNPUBLISHED,
        LibraryItemUnpublishedRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.LIBRARY_QUEUE_WAITING, LibraryQueueWaitingRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.LIBRARY_REPORT_FILED, LibraryReportFiledRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.LIBRARY_READING_LIST_NEW,
        LibraryReadingListNewRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.LIBRARY_SUGGESTION_APPROVED,
        LibrarySuggestionApprovedRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.LIBRARY_SUGGESTION_DECLINED,
        LibrarySuggestionDeclinedRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.CURATOR_EXAM_MARK, CuratorExamMarkRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.LESSON_ABSENCE, LessonAbsenceRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.CURATOR_ABSENCES, CuratorAbsencesRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.TEACHER_TEMPORARY_MARKS,
        TeacherTemporaryMarksRenderer(i18n, urls),
    )
    registry.register(NotificationType.LMS_REVIEW_DUE, LmsReviewDueRenderer(i18n, urls))
    registry.register(
        NotificationType.LMS_STREAK_AT_RISK, LmsStreakAtRiskRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.LMS_DEADLINE_SOON, LmsDeadlineSoonRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.EVENT_REMINDER, EventReminderRenderer(i18n, urls)
    )
    registry.register(NotificationType.EVENT_CHANGED, EventChangedRenderer(i18n, urls))
    registry.register(
        NotificationType.EVENT_CANCELLED, EventCancelledRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.EVENT_RATING_REQUEST, EventRatingRequestRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.CLUB_ANNOUNCEMENT, ClubAnnouncementRenderer(i18n, urls, files)
    )
    registry.register(
        NotificationType.CLUB_JOIN_REQUEST, ClubJoinRequestRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.CLUB_JOIN_RESULT, ClubJoinResultRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.CLUB_TRANSFER_OFFER, ClubTransferOfferRenderer(i18n, urls)
    )
    registry.register(NotificationType.DRAFT_INVITE, DraftInviteRenderer(i18n, urls))
    registry.register(
        NotificationType.POSITION_APPLICATION_RESULT,
        PositionApplicationResultRenderer(i18n, urls),
    )
    registry.register(
        NotificationType.CLUB_OWNER_GRADUATING, ClubOwnerGraduatingRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.HOMEWORK_SUBMITTED, HomeworkSubmittedRenderer(i18n, urls)
    )
    registry.register(
        NotificationType.HOMEWORK_REVIEWED, HomeworkReviewedRenderer(i18n, urls)
    )
