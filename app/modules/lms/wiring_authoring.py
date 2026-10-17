"""Wiring of course authoring: repositories, use cases and public contracts."""

from dataclasses import dataclass

from app.modules.lms.application.authoring.add_course_staff import AddCourseStaff
from app.modules.lms.application.authoring.append_block import AppendBlock
from app.modules.lms.application.authoring.append_question import AppendQuestion
from app.modules.lms.application.authoring.apply_course_plan import ApplyCoursePlan
from app.modules.lms.application.authoring.apply_outline_ops import ApplyOutlineOps
from app.modules.lms.application.authoring.archive_course import ArchiveCourse
from app.modules.lms.application.authoring.compare_versions import CompareVersions
from app.modules.lms.application.authoring.create_course import CreateCourse
from app.modules.lms.application.authoring.create_section import CreateSection
from app.modules.lms.application.authoring.create_step import CreateStep
from app.modules.lms.application.authoring.discard_course import DiscardCourse
from app.modules.lms.application.authoring.discard_step import DiscardStep
from app.modules.lms.application.authoring.draft_writer import StepDraftWriter
from app.modules.lms.application.authoring.ensure_preview_revision import (
    EnsurePreviewRevision,
)
from app.modules.lms.application.authoring.get_course_draft import GetCourseDraft
from app.modules.lms.application.authoring.get_course_settings import (
    GetCourseSettings,
)
from app.modules.lms.application.authoring.get_pending_changes import (
    GetPendingChanges,
)
from app.modules.lms.application.authoring.get_step_diff import GetStepDiff
from app.modules.lms.application.authoring.get_step_draft import GetStepDraft
from app.modules.lms.application.authoring.get_version import GetVersion
from app.modules.lms.application.authoring.list_course_attempts import (
    ListCourseAttempts,
)
from app.modules.lms.application.authoring.list_course_staff import ListCourseStaff
from app.modules.lms.application.authoring.list_courses_for_staff import (
    ListCoursesForStaff,
)
from app.modules.lms.application.authoring.list_step_history import ListStepHistory
from app.modules.lms.application.authoring.list_versions import ListVersions
from app.modules.lms.application.authoring.outline_editor import OutlineEditor
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.preview_h5p import PreviewH5P
from app.modules.lms.application.authoring.preview_step import PreviewStep
from app.modules.lms.application.authoring.preview_video import PreviewVideo
from app.modules.lms.application.authoring.prune_revisions import PruneRevisions
from app.modules.lms.application.authoring.publish_course import PublishCourse
from app.modules.lms.application.authoring.regenerate_join_code import (
    RegenerateJoinCode,
)
from app.modules.lms.application.authoring.remove_course_staff import (
    RemoveCourseStaff,
)
from app.modules.lms.application.authoring.restore_revision import RestoreRevision
from app.modules.lms.application.authoring.restore_version import RestoreVersion
from app.modules.lms.application.authoring.rotate_invite_code import RotateInviteCode
from app.modules.lms.application.authoring.save_checkpoint import SaveCheckpoint
from app.modules.lms.application.authoring.save_step_draft import SaveStepDraft
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.update_course_details import (
    UpdateCourseDetails,
)
from app.modules.lms.application.authoring.update_course_meta import UpdateCourseMeta
from app.modules.lms.application.authoring.update_course_settings import (
    UpdateCourseSettings,
)
from app.modules.lms.application.authoring.update_course_staff import UpdateCourseStaff
from app.modules.lms.application.authoring.upload_h5p import UploadH5P
from app.modules.lms.application.authoring.validate_links import (
    GetLinkReport,
    StartLinkCheck,
    ValidateLinks,
)
from app.modules.lms.application.h5p_links import H5PLinks
from app.modules.lms.application.public_authoring import (
    LmsDraftCommandsImpl,
    LmsQueriesImpl,
)
from app.modules.lms.application.public_workspace import (
    LmsWorkspaceCommandsImpl,
    LmsWorkspaceImpl,
)
from app.modules.lms.infrastructure.authoring.http_link_checker import (
    HttpLinkChecker,
)
from app.modules.lms.infrastructure.authoring.uow import SqlAuthoringUnitOfWork
from app.modules.lms.infrastructure.h5p_memory_store import MemoryH5PStore
from app.modules.lms.ports.authoring.link_checker import LinkChecker
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.modules.lms.ports.h5p_store import H5PObjectStore
from app.shared.clock import Clock
from app.shared.contracts.academic import GroupDirectory
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.tasks import TaskKicker
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class AuthoringServices:
    """Use cases of course authoring plus the contracts other modules consume."""

    create_course: CreateCourse
    update_course_settings: UpdateCourseSettings
    rotate_invite_code: RotateInviteCode
    list_course_staff: ListCourseStaff
    add_course_staff: AddCourseStaff
    update_course_staff: UpdateCourseStaff
    remove_course_staff: RemoveCourseStaff
    get_course_draft: GetCourseDraft
    update_course_meta: UpdateCourseMeta
    apply_outline_ops: ApplyOutlineOps
    create_section: CreateSection
    create_step: CreateStep
    get_step_draft: GetStepDraft
    save_step_draft: SaveStepDraft
    discard_step: DiscardStep
    discard_course: DiscardCourse
    save_checkpoint: SaveCheckpoint
    list_step_history: ListStepHistory
    restore_revision: RestoreRevision
    get_step_diff: GetStepDiff
    get_pending_changes: GetPendingChanges
    publish_course: PublishCourse
    list_versions: ListVersions
    get_version: GetVersion
    compare_versions: CompareVersions
    restore_version: RestoreVersion
    preview_step: PreviewStep
    preview_video: PreviewVideo
    preview_h5p: PreviewH5P
    upload_h5p: UploadH5P
    ensure_preview_revision: EnsurePreviewRevision
    prune_revisions: PruneRevisions
    queries: LmsQueriesImpl
    draft_commands: LmsDraftCommandsImpl
    workspace: LmsWorkspaceImpl
    workspace_commands: LmsWorkspaceCommandsImpl
    get_course_settings: GetCourseSettings
    update_course_details: UpdateCourseDetails
    regenerate_join_code: RegenerateJoinCode
    start_link_check: StartLinkCheck
    get_link_report: GetLinkReport
    validate_links: ValidateLinks


def build_authoring(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    files: FilesApi,
    h5p_links: H5PLinks | None = None,
    groups: GroupDirectory | None = None,
) -> AuthoringServices:
    """Build the authoring use cases on SQL repositories."""

    def uow_factory() -> AuthoringUnitOfWork:
        return SqlAuthoringUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return assemble_authoring(
        uow_factory,
        clock=deps.clock,
        identity=identity,
        files=files,
        kicker=deps.kicker,
        h5p_links=h5p_links,
        groups=groups,
    )


def assemble_authoring(
    uow_factory: UowFactory,
    *,
    clock: Clock,
    identity: IdentityDirectory,
    files: FilesApi,
    kicker: TaskKicker | None = None,
    link_checker: LinkChecker | None = None,
    h5p_links: H5PLinks | None = None,
    groups: GroupDirectory | None = None,
) -> AuthoringServices:
    """Connect use cases to a unit of work factory (SQL, or fakes in tests)."""
    if h5p_links is None:
        h5p_links = H5PLinks(b"lms-h5p-test-key", clock, MemoryH5PStore())
    h5p_store: H5PObjectStore = h5p_links.store or MemoryH5PStore()
    presenter = Presenter(identity)
    writer = StepDraftWriter(files)
    editor = OutlineEditor(presenter, clock)
    get_course_draft = GetCourseDraft(uow_factory, presenter)
    get_step_draft = GetStepDraft(uow_factory, presenter)
    get_pending_changes = GetPendingChanges(uow_factory, presenter)
    list_versions = ListVersions(uow_factory, presenter)
    save_step_draft = SaveStepDraft(uow_factory, clock, presenter, writer)
    create_section = CreateSection(uow_factory, editor)
    create_step = CreateStep(uow_factory, clock, presenter)
    create_course = CreateCourse(uow_factory, clock, presenter)
    update_course_meta = UpdateCourseMeta(uow_factory, clock, presenter)
    apply_outline_ops = ApplyOutlineOps(uow_factory, editor, presenter)
    return AuthoringServices(
        create_course=create_course,
        update_course_settings=UpdateCourseSettings(uow_factory, presenter, writer),
        rotate_invite_code=RotateInviteCode(uow_factory),
        list_course_staff=ListCourseStaff(uow_factory, presenter),
        add_course_staff=AddCourseStaff(uow_factory, presenter, identity),
        update_course_staff=UpdateCourseStaff(uow_factory, presenter),
        remove_course_staff=RemoveCourseStaff(uow_factory),
        get_course_draft=get_course_draft,
        update_course_meta=update_course_meta,
        apply_outline_ops=apply_outline_ops,
        create_section=create_section,
        create_step=create_step,
        get_step_draft=get_step_draft,
        save_step_draft=save_step_draft,
        discard_step=DiscardStep(uow_factory, clock, presenter),
        discard_course=DiscardCourse(uow_factory, clock, presenter),
        save_checkpoint=SaveCheckpoint(uow_factory, clock, presenter),
        list_step_history=ListStepHistory(uow_factory, presenter),
        restore_revision=RestoreRevision(uow_factory, clock, presenter),
        get_step_diff=GetStepDiff(uow_factory),
        get_pending_changes=get_pending_changes,
        publish_course=PublishCourse(uow_factory, clock, presenter, kicker),
        list_versions=list_versions,
        get_version=GetVersion(uow_factory, presenter),
        compare_versions=CompareVersions(uow_factory),
        restore_version=RestoreVersion(uow_factory, clock, presenter),
        preview_step=PreviewStep(uow_factory),
        preview_video=PreviewVideo(uow_factory, files),
        preview_h5p=PreviewH5P(uow_factory, h5p_links),
        upload_h5p=UploadH5P(uow_factory, h5p_store),
        ensure_preview_revision=EnsurePreviewRevision(uow_factory, clock),
        prune_revisions=PruneRevisions(uow_factory, clock),
        queries=LmsQueriesImpl(
            list_courses=ListCoursesForStaff(uow_factory, identity),
            get_course_draft=get_course_draft,
            get_step_draft=get_step_draft,
            get_pending_changes=get_pending_changes,
            list_versions=list_versions,
            list_attempts=ListCourseAttempts(uow_factory),
        ),
        draft_commands=LmsDraftCommandsImpl(
            create_section=create_section,
            create_step=create_step,
            append_block=AppendBlock(get_step_draft, save_step_draft),
            append_question=AppendQuestion(get_step_draft, save_step_draft),
            create_course=create_course,
            update_course_meta=update_course_meta,
            archive_course=ArchiveCourse(uow_factory),
            apply_outline_ops=apply_outline_ops,
            get_course_draft=get_course_draft,
            get_step_draft=get_step_draft,
            save_step_draft=save_step_draft,
        ),
        workspace=LmsWorkspaceImpl(
            uow_factory=uow_factory,
            identity=identity,
            get_course_draft=get_course_draft,
        ),
        workspace_commands=LmsWorkspaceCommandsImpl(
            apply_course_plan=ApplyCoursePlan(uow_factory, clock, writer),
            save_step_draft=save_step_draft,
        ),
        get_course_settings=GetCourseSettings(uow_factory),
        update_course_details=UpdateCourseDetails(uow_factory, writer, groups),
        regenerate_join_code=RegenerateJoinCode(uow_factory),
        start_link_check=StartLinkCheck(uow_factory, clock, kicker),
        get_link_report=GetLinkReport(uow_factory),
        validate_links=ValidateLinks(
            uow_factory, link_checker or HttpLinkChecker(), clock
        ),
    )
