"""Builds the notebooks module: use cases, jobs and the public API for the assistant."""

import asyncio
from dataclasses import dataclass

from app.modules.notebooks.application.add_default_material import AddDefaultMaterial
from app.modules.notebooks.application.add_sources import AddSources
from app.modules.notebooks.application.apply_course_artifact import ApplyCourseArtifact
from app.modules.notebooks.application.ask_notebook import AskNotebook
from app.modules.notebooks.application.attach_artifact import AttachArtifactToLesson
from app.modules.notebooks.application.build_source_guide import BuildSourceGuide
from app.modules.notebooks.application.cancel_artifact import CancelArtifact
from app.modules.notebooks.application.confirm_presentation_plan import (
    ConfirmPresentationPlan,
)
from app.modules.notebooks.application.copy_notebook import CopyNotebook
from app.modules.notebooks.application.create_label import CreateLabel
from app.modules.notebooks.application.create_notebook import CreateNotebook
from app.modules.notebooks.application.create_presentation_plan import (
    CreatePresentationPlan,
)
from app.modules.notebooks.application.delete_artifact import DeleteArtifact
from app.modules.notebooks.application.delete_chat import DeleteChat
from app.modules.notebooks.application.delete_label import DeleteLabel
from app.modules.notebooks.application.delete_notebook import DeleteNotebook
from app.modules.notebooks.application.delete_owner import DeleteOwner
from app.modules.notebooks.application.discover_sources import DiscoverSources
from app.modules.notebooks.application.edit_slides import EditSlides
from app.modules.notebooks.application.embed_passages import EmbedPassages
from app.modules.notebooks.application.gather_web_materials import GatherWebMaterials
from app.modules.notebooks.application.generate_artifact import GenerateArtifact
from app.modules.notebooks.application.get_artifact import GetArtifact
from app.modules.notebooks.application.get_chat import GetChat
from app.modules.notebooks.application.get_notebook import GetNotebook
from app.modules.notebooks.application.get_notebook_usage import GetNotebookUsage
from app.modules.notebooks.application.get_passage import GetPassage
from app.modules.notebooks.application.get_presentation_plan import (
    GetPresentationPlan,
)
from app.modules.notebooks.application.get_source import GetSource
from app.modules.notebooks.application.get_usage import GetUsage
from app.modules.notebooks.application.label_sources import LabelSources
from app.modules.notebooks.application.light_json import Sleep
from app.modules.notebooks.application.list_artifacts import ListArtifacts
from app.modules.notebooks.application.list_course_steps import ListCourseSteps
from app.modules.notebooks.application.list_default_materials import (
    ListDefaultMaterials,
)
from app.modules.notebooks.application.list_labels import ListLabels
from app.modules.notebooks.application.list_notebooks import ListNotebooks
from app.modules.notebooks.application.list_passages import ListPassages
from app.modules.notebooks.application.list_sources import ListSources
from app.modules.notebooks.application.list_subject_slots import ListSubjectSlots
from app.modules.notebooks.application.message_feedback import MessageFeedback
from app.modules.notebooks.application.open_auto_notebook import OpenAutoNotebook
from app.modules.notebooks.application.open_course_workspace import (
    OpenCourseWorkspace,
)
from app.modules.notebooks.application.process_source import ProcessSource
from app.modules.notebooks.application.provision_course_notebook import (
    BackfillCourseNotebooks,
    ProvisionCourseNotebook,
)
from app.modules.notebooks.application.provision_student_notebooks import (
    BackfillSubjectNotebooks,
    ProvisionStudentNotebooks,
)
from app.modules.notebooks.application.public_api import NotebooksQueriesImpl
from app.modules.notebooks.application.public_commands import NotebooksCommandsImpl
from app.modules.notebooks.application.purge_deleted import PurgeDeleted
from app.modules.notebooks.application.purge_shared import PurgeShared
from app.modules.notebooks.application.reconcile_subject_materials import (
    ReconcileSubjectMaterials,
)
from app.modules.notebooks.application.refresh_summaries import RefreshSummaries
from app.modules.notebooks.application.regenerate_chat import RegenerateChat
from app.modules.notebooks.application.remove_default_material import (
    RemoveDefaultMaterial,
)
from app.modules.notebooks.application.remove_source import RemoveSource
from app.modules.notebooks.application.rename_artifact import RenameArtifact
from app.modules.notebooks.application.request_artifact import RequestArtifact
from app.modules.notebooks.application.retry_artifact import RetryArtifact
from app.modules.notebooks.application.revise_slides import ReviseSlides
from app.modules.notebooks.application.save_as_source import SaveAsSource
from app.modules.notebooks.application.save_flashcard_set import SaveFlashcardSet
from app.modules.notebooks.application.save_note import SaveNote
from app.modules.notebooks.application.save_progress import SaveProgress
from app.modules.notebooks.application.save_to_files import SaveArtifactToFiles
from app.modules.notebooks.application.search_sources import SearchSources
from app.modules.notebooks.application.select_sources import SelectSources
from app.modules.notebooks.application.set_source_labels import SetSourceLabels
from app.modules.notebooks.application.shared_passage_search import (
    SharedPassageSearch,
)
from app.modules.notebooks.application.staff_subject_materials import (
    StaffSubjectMaterials,
)
from app.modules.notebooks.application.start_labeling import StartLabeling
from app.modules.notebooks.application.sweep_auto_notebooks import SweepAutoNotebooks
from app.modules.notebooks.application.sweep_sources import SweepSources
from app.modules.notebooks.application.sweep_stuck import SweepStuck
from app.modules.notebooks.application.sync_auto_notebook import SyncAutoNotebook
from app.modules.notebooks.application.sync_course_notebook import (
    SyncCourseNotebook,
    SyncCourseNotebooks,
)
from app.modules.notebooks.application.sync_lesson_notebooks import SyncLessonNotebooks
from app.modules.notebooks.application.sync_source import SyncSource
from app.modules.notebooks.application.update_auto_settings import UpdateAutoSettings
from app.modules.notebooks.application.update_label import UpdateLabel
from app.modules.notebooks.application.update_notebook import UpdateNotebook
from app.modules.notebooks.application.update_presentation_plan import (
    UpdatePresentationPlan,
)
from app.modules.notebooks.application.update_source import UpdateSource
from app.modules.notebooks.infrastructure.repositories.shared_passage_repository import (  # noqa: E501
    SqlSharedPassageReader,
)
from app.modules.notebooks.ports.term_calendar import TermCalendar
from app.modules.notebooks.ports.web_fetcher import WebFetcher
from app.modules.notebooks.wiring_auto import build_auto
from app.modules.notebooks.wiring_chat import build_chat
from app.modules.notebooks.wiring_core import CoreOverrides, build_core
from app.modules.notebooks.wiring_course import build_course
from app.modules.notebooks.wiring_labels import build_labels
from app.modules.notebooks.wiring_notebooks import build_notebooks
from app.modules.notebooks.wiring_sources import build_sources
from app.modules.notebooks.wiring_studio import LmsApplyPorts, build_studio
from app.modules.notebooks.wiring_workspace import build_workspace
from app.shared.contracts.academic import ClassworkQueries, ScheduleQueries
from app.shared.contracts.ai import AiQueries, LlmGateway
from app.shared.contracts.embeddings import EmbeddingIndex
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.library import LibraryQueries, LibrarySourceReader
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import LmsSourceReader, LmsWorkspace
from app.shared.contracts.notebooks import NotebooksCommands, NotebooksQueries
from app.shared.contracts.web_search import WebSearchApi
from app.shared.wiring import ModuleDeps


@dataclass(frozen=True, slots=True)
class NotebooksServices:
    """Use cases of the notebooks module (attribute name = use case file name)."""

    create_notebook: CreateNotebook
    list_notebooks: ListNotebooks
    get_notebook: GetNotebook
    update_notebook: UpdateNotebook
    copy_notebook: CopyNotebook
    delete_notebook: DeleteNotebook
    purge_deleted: PurgeDeleted
    purge_shared: PurgeShared
    delete_owner: DeleteOwner
    sweep_stuck: SweepStuck
    add_sources: AddSources
    discover_sources: DiscoverSources
    list_sources: ListSources
    get_source: GetSource
    update_source: UpdateSource
    select_sources: SelectSources
    sync_source: SyncSource
    remove_source: RemoveSource
    list_passages: ListPassages
    get_passage: GetPassage
    search_sources: SearchSources
    process_source: ProcessSource
    embed_passages: EmbedPassages
    build_source_guide: BuildSourceGuide
    refresh_summaries: RefreshSummaries
    sweep_sources: SweepSources
    gather_web_materials: GatherWebMaterials
    open_auto_notebook: OpenAutoNotebook
    list_subject_slots: ListSubjectSlots
    update_auto_settings: UpdateAutoSettings
    sync_auto_notebook: SyncAutoNotebook
    sync_lesson_notebooks: SyncLessonNotebooks
    sweep_auto_notebooks: SweepAutoNotebooks
    provision_student_notebooks: ProvisionStudentNotebooks
    backfill_subject_notebooks: BackfillSubjectNotebooks
    list_default_materials: ListDefaultMaterials
    add_default_material: AddDefaultMaterial
    remove_default_material: RemoveDefaultMaterial
    staff_subject_materials: StaffSubjectMaterials
    reconcile_subject_materials: ReconcileSubjectMaterials
    provision_course_notebook: ProvisionCourseNotebook
    sync_course_notebook: SyncCourseNotebook
    sync_course_notebooks: SyncCourseNotebooks
    backfill_course_notebooks: BackfillCourseNotebooks
    get_chat: GetChat
    ask_notebook: AskNotebook
    regenerate_chat: RegenerateChat
    delete_chat: DeleteChat
    message_feedback: MessageFeedback
    save_note: SaveNote
    request_artifact: RequestArtifact
    generate_artifact: GenerateArtifact
    list_artifacts: ListArtifacts
    get_artifact: GetArtifact
    rename_artifact: RenameArtifact
    delete_artifact: DeleteArtifact
    cancel_artifact: CancelArtifact
    retry_artifact: RetryArtifact
    save_progress: SaveProgress
    save_as_source: SaveAsSource
    attach_artifact: AttachArtifactToLesson | None
    save_to_files: SaveArtifactToFiles | None
    save_flashcard_set: SaveFlashcardSet
    edit_slides: EditSlides
    revise_slides: ReviseSlides
    create_presentation_plan: CreatePresentationPlan
    get_presentation_plan: GetPresentationPlan
    update_presentation_plan: UpdatePresentationPlan
    confirm_presentation_plan: ConfirmPresentationPlan
    apply_course_artifact: ApplyCourseArtifact
    get_usage: GetUsage
    open_course_workspace: OpenCourseWorkspace
    get_notebook_usage: GetNotebookUsage
    list_course_steps: ListCourseSteps
    list_labels: ListLabels
    create_label: CreateLabel
    update_label: UpdateLabel
    delete_label: DeleteLabel
    set_source_labels: SetSourceLabels
    start_labeling: StartLabeling
    label_sources: LabelSources
    public: NotebooksQueries
    commands: NotebooksCommands
    shared_search: SharedPassageSearch


def build(
    deps: ModuleDeps,
    *,
    llm: LlmGateway,
    identity: IdentityDirectory,
    files: FilesApi,
    ai: AiQueries,
    links: LinksApi,
    schedule: ScheduleQueries,
    flashcards: FlashcardsApi,
    lms: LmsSourceReader | None = None,
    fetcher: WebFetcher | None = None,
    classwork: ClassworkQueries | None = None,
    terms: TermCalendar | None = None,
    overrides: CoreOverrides | None = None,
    sleep: Sleep = asyncio.sleep,
    web_search: WebSearchApi | None = None,
    lms_apply: LmsApplyPorts | None = None,
    workspace: LmsWorkspace | None = None,
    embeddings: EmbeddingIndex | None = None,
    library: LibrarySourceReader | None = None,
    library_queries: LibraryQueries | None = None,
) -> NotebooksServices:
    """Wire the module over the other modules' public APIs.

    `lms` and `fetcher` may be None: LMS steps and web pages are then unsupported.
    `library` may be None: library books and notes are then unsupported as sources.
    `classwork` and `terms` may be None: subject and lesson notebooks are then off.
    `web_search` may be None: the web toggle and Discover then answer `disabled`.
    `lms_apply` carries the LMS ports of "Apply to the course"; None turns it off.
    `workspace` (the LMS side of course workspaces: access, outline, draft steps) may
    be None: no course workspace can be opened then.
    `embeddings` (the vectors module) may be None: retrieval is then lexical only.
    The assistant reaches the module through `public` and `commands`
    (`ai.bindings.notebooks`, `ai.bindings.notebooks_commands`).
    """
    core = build_core(
        deps,
        gateway=llm,
        identity=identity,
        overrides=overrides,
        web_search=web_search,
        workspace=workspace,
        embeddings=embeddings,
    )
    notebooks = build_notebooks(core)
    workspaces = build_workspace(core)
    sources = build_sources(
        core,
        files=files,
        ai=ai,
        links=links,
        schedule=schedule,
        flashcards=flashcards,
        lms=lms,
        fetcher=fetcher,
        sleep=sleep,
        library=library,
        identity=identity,
    )
    auto = build_auto(
        core,
        readers=sources.readers,
        links=links,
        schedule=schedule,
        classwork=classwork,
        terms=terms,
        library=library_queries,
        identity=identity,
        files=files,
    )
    course = build_course(core, readers=sources.readers, lms=lms, files=files)
    chat = build_chat(core)
    labels = build_labels(core, sleep=sleep)
    studio = build_studio(
        core,
        flashcards=flashcards,
        files=files,
        links=links,
        sleep=sleep,
        lms_apply=lms_apply,
    )
    return NotebooksServices(
        create_notebook=notebooks.create_notebook,
        list_notebooks=notebooks.list_notebooks,
        get_notebook=notebooks.get_notebook,
        update_notebook=notebooks.update_notebook,
        copy_notebook=notebooks.copy_notebook,
        delete_notebook=notebooks.delete_notebook,
        purge_deleted=notebooks.purge_deleted,
        purge_shared=notebooks.purge_shared,
        delete_owner=notebooks.delete_owner,
        sweep_stuck=notebooks.sweep_stuck,
        add_sources=sources.add_sources,
        discover_sources=sources.discover_sources,
        list_sources=sources.list_sources,
        get_source=sources.get_source,
        update_source=sources.update_source,
        select_sources=sources.select_sources,
        sync_source=sources.sync_source,
        remove_source=sources.remove_source,
        list_passages=sources.list_passages,
        get_passage=sources.get_passage,
        search_sources=sources.search_sources,
        process_source=sources.process_source,
        embed_passages=sources.embed_passages,
        build_source_guide=sources.build_source_guide,
        refresh_summaries=sources.refresh_summaries,
        sweep_sources=sources.sweep_sources,
        gather_web_materials=sources.gather_web_materials,
        open_auto_notebook=auto.open_auto_notebook,
        list_subject_slots=auto.list_subject_slots,
        update_auto_settings=auto.update_auto_settings,
        sync_auto_notebook=auto.sync_auto_notebook,
        sync_lesson_notebooks=auto.sync_lesson_notebooks,
        sweep_auto_notebooks=auto.sweep_auto_notebooks,
        provision_student_notebooks=auto.provision_student_notebooks,
        backfill_subject_notebooks=auto.backfill_subject_notebooks,
        list_default_materials=auto.list_default_materials,
        add_default_material=auto.add_default_material,
        remove_default_material=auto.remove_default_material,
        staff_subject_materials=auto.staff_subject_materials,
        reconcile_subject_materials=auto.reconcile_subject_materials,
        provision_course_notebook=course.provision_course_notebook,
        sync_course_notebook=course.sync_course_notebook,
        sync_course_notebooks=course.sync_course_notebooks,
        backfill_course_notebooks=course.backfill_course_notebooks,
        get_chat=chat.get_chat,
        ask_notebook=chat.ask_notebook,
        regenerate_chat=chat.regenerate_chat,
        delete_chat=chat.delete_chat,
        message_feedback=chat.message_feedback,
        save_note=chat.save_note,
        request_artifact=studio.request_artifact,
        generate_artifact=studio.generate_artifact,
        list_artifacts=studio.list_artifacts,
        get_artifact=studio.get_artifact,
        rename_artifact=studio.rename_artifact,
        delete_artifact=studio.delete_artifact,
        cancel_artifact=studio.cancel_artifact,
        retry_artifact=studio.retry_artifact,
        save_progress=studio.save_progress,
        save_as_source=studio.save_as_source,
        attach_artifact=studio.attach_artifact,
        save_to_files=studio.save_to_files,
        save_flashcard_set=studio.save_flashcard_set,
        edit_slides=studio.edit_slides,
        revise_slides=studio.revise_slides,
        create_presentation_plan=studio.create_presentation_plan,
        get_presentation_plan=studio.get_presentation_plan,
        update_presentation_plan=studio.update_presentation_plan,
        confirm_presentation_plan=studio.confirm_presentation_plan,
        apply_course_artifact=studio.apply_course_artifact,
        get_usage=core.usage,
        open_course_workspace=workspaces.open_course_workspace,
        get_notebook_usage=workspaces.get_notebook_usage,
        list_course_steps=workspaces.list_course_steps,
        list_labels=labels.list_labels,
        create_label=labels.create_label,
        update_label=labels.update_label,
        delete_label=labels.delete_label,
        set_source_labels=labels.set_source_labels,
        start_labeling=labels.start_labeling,
        label_sources=labels.label_sources,
        public=NotebooksQueriesImpl(core.uow_factory, core.quota, core.embeddings),
        shared_search=SharedPassageSearch(
            reader=SqlSharedPassageReader(deps.sessionmaker),
            library=library,
            schedule=schedule,
            embeddings=core.embeddings,
        ),
        commands=NotebooksCommandsImpl(
            create_notebook=notebooks.create_notebook,
            add_sources=sources.add_sources,
            request_artifact=studio.request_artifact,
            apply_artifact=studio.apply_course_artifact,
            open_course_workspace=workspaces.open_course_workspace,
        ),
    )
