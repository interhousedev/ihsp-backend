"""Wiring of the Studio slice: the use cases that make and manage outputs."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.modules.notebooks.application.apply_course_artifact import ApplyCourseArtifact
from app.modules.notebooks.application.attach_artifact import AttachArtifactToLesson
from app.modules.notebooks.application.cancel_artifact import CancelArtifact
from app.modules.notebooks.application.delete_artifact import DeleteArtifact
from app.modules.notebooks.application.edit_slides import EditSlides
from app.modules.notebooks.application.generate_artifact import GenerateArtifact
from app.modules.notebooks.application.get_artifact import GetArtifact
from app.modules.notebooks.application.list_artifacts import ListArtifacts
from app.modules.notebooks.application.rename_artifact import RenameArtifact
from app.modules.notebooks.application.request_artifact import RequestArtifact
from app.modules.notebooks.application.retry_artifact import RetryArtifact
from app.modules.notebooks.application.revise_slides import ReviseSlides
from app.modules.notebooks.application.save_as_source import SaveAsSource
from app.modules.notebooks.application.save_flashcard_set import SaveFlashcardSet
from app.modules.notebooks.application.save_progress import SaveProgress
from app.modules.notebooks.application.save_to_files import SaveArtifactToFiles
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import LmsDraftCommands, LmsQueries, LmsWorkspaceCommands


@dataclass(frozen=True, slots=True)
class LmsApplyPorts:
    """The LMS ports "Apply to the course" writes through; a missing one turns it off.

    Wire them from the LMS authoring services: ``workspace_commands`` (outline and
    replace step), ``queries`` (the draft of a step, the course) and
    ``draft_commands`` (a new step).
    """

    workspace: LmsWorkspaceCommands | None = None
    queries: LmsQueries | None = None
    drafts: LmsDraftCommands | None = None


@dataclass(frozen=True, slots=True)
class StudioServices:
    """Studio use cases; the attribute is the name of its file."""

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
    save_flashcard_set: SaveFlashcardSet
    edit_slides: EditSlides
    revise_slides: ReviseSlides
    apply_course_artifact: ApplyCourseArtifact
    attach_artifact: AttachArtifactToLesson | None
    save_to_files: SaveArtifactToFiles | None


def build_studio(
    core: NotebooksCore,
    *,
    flashcards: FlashcardsApi,
    files: FilesApi | None = None,
    links: LinksApi | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    lms_apply: LmsApplyPorts | None = None,
) -> StudioServices:
    """Build the Studio use cases over the shared services.

    Args:
        core: The shared collaborators of the module.
        flashcards: Creates flash card sets for "Save as flash card set".
        files: Stores the file of "Attach to lesson" (None: the route answers 404).
        links: Adds that file to a lesson (with `files`).
        sleep: Waits between provider retries (replaced in tests).
        lms_apply: The LMS ports of "Apply to the course" (None: the routes answer
            feature-disabled).
    """
    deps = core.deps
    uow_factory, clock, settings = core.uow_factory, deps.clock, deps.settings
    ports = lms_apply or LmsApplyPorts()
    return StudioServices(
        request_artifact=RequestArtifact(
            uow_factory=uow_factory,
            budget=core.budget,
            quota=core.quota,
            kicker=deps.kicker,
            clock=clock,
            settings=settings,
            locale=core.locale,
        ),
        generate_artifact=GenerateArtifact(
            uow_factory=uow_factory,
            llm=core.llm,
            budget=core.budget,
            quota=core.quota,
            locale=core.locale,
            context=core.context,
            clock=clock,
            settings=settings,
            sleep=sleep,
            course_context=core.course_context,
        ),
        list_artifacts=ListArtifacts(uow_factory=uow_factory),
        get_artifact=GetArtifact(uow_factory=uow_factory, clock=clock),
        rename_artifact=RenameArtifact(uow_factory=uow_factory, clock=clock),
        delete_artifact=DeleteArtifact(
            uow_factory=uow_factory, quota=core.quota, clock=clock
        ),
        cancel_artifact=CancelArtifact(
            uow_factory=uow_factory, quota=core.quota, clock=clock
        ),
        retry_artifact=RetryArtifact(
            uow_factory=uow_factory,
            budget=core.budget,
            quota=core.quota,
            kicker=deps.kicker,
            clock=clock,
            settings=settings,
        ),
        save_progress=SaveProgress(uow_factory=uow_factory, clock=clock),
        save_as_source=SaveAsSource(
            uow_factory=uow_factory, kicker=deps.kicker, clock=clock, settings=settings
        ),
        save_flashcard_set=SaveFlashcardSet(
            uow_factory=uow_factory, flashcards=flashcards, clock=clock
        ),
        edit_slides=EditSlides(uow_factory=uow_factory, clock=clock),
        revise_slides=ReviseSlides(
            uow_factory=uow_factory,
            budget=core.budget,
            quota=core.quota,
            kicker=deps.kicker,
            clock=clock,
            settings=settings,
        ),
        apply_course_artifact=ApplyCourseArtifact(
            uow_factory=uow_factory,
            workspace=ports.workspace,
            queries=ports.queries,
            drafts=ports.drafts,
        ),
        attach_artifact=(
            AttachArtifactToLesson(uow_factory=uow_factory, files=files, links=links)
            if files is not None and links is not None
            else None
        ),
        save_to_files=(
            SaveArtifactToFiles(uow_factory=uow_factory, files=files)
            if files is not None
            else None
        ),
    )
