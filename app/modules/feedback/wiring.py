"""Builds the feedback module (container.feedback)."""

from dataclasses import dataclass

from app.modules.feedback.application.get_feedback import GetFeedback
from app.modules.feedback.application.get_my_feedback import GetMyFeedback
from app.modules.feedback.application.list_feedback import ListFeedback
from app.modules.feedback.application.list_my_feedback import ListMyFeedback
from app.modules.feedback.application.respond_to_feedback import RespondToFeedback
from app.modules.feedback.application.set_feedback_status import SetFeedbackStatus
from app.modules.feedback.application.submit_feedback import SubmitFeedback
from app.modules.feedback.application.views import FeedbackPresenter
from app.modules.feedback.infrastructure.uow import SqlFeedbackUnitOfWork
from app.modules.feedback.ports.people import FeedbackMailer, PeopleDirectory
from app.modules.feedback.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FilesApi
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class FeedbackServices:
    """Use cases of the feedback module.

    ``submit`` is callable: ``await container.feedback.submit(actor, kind, area,
    title, description, attachment_file_ids, source="bot")``.
    """

    submit: SubmitFeedback
    list_mine: ListMyFeedback
    get_mine: GetMyFeedback
    list_all: ListFeedback
    get: GetFeedback
    set_status: SetFeedbackStatus
    respond: RespondToFeedback


@dataclass(frozen=True, slots=True)
class FeedbackOverrides:
    """Replacement for the SQL unit of work (for tests)."""

    uow_factory: UowFactory | None = None


def build(
    deps: ModuleDeps,
    *,
    files: FilesApi,
    people: PeopleDirectory,
    mailer: FeedbackMailer | None,
    overrides: FeedbackOverrides | None = None,
) -> FeedbackServices:
    """Wire the module; without ``mailer`` mail deliveries are ``unavailable``."""
    over = overrides or FeedbackOverrides()
    uow_factory = over.uow_factory or _sql_uow_factory(deps)
    presenter = FeedbackPresenter(files=files, people=people)
    get = GetFeedback(uow_factory=uow_factory, presenter=presenter)
    return FeedbackServices(
        submit=SubmitFeedback(
            uow_factory=uow_factory,
            files=files,
            people=people,
            presenter=presenter,
            rate_limiter=deps.rate_limiter,
            clock=deps.clock,
        ),
        list_mine=ListMyFeedback(uow_factory=uow_factory, presenter=presenter),
        get_mine=GetMyFeedback(uow_factory=uow_factory, presenter=presenter),
        list_all=ListFeedback(uow_factory=uow_factory, presenter=presenter),
        get=get,
        set_status=SetFeedbackStatus(
            uow_factory=uow_factory, clock=deps.clock, get=get
        ),
        respond=RespondToFeedback(
            uow_factory=uow_factory,
            files=files,
            people=people,
            mailer=mailer,
            presenter=presenter,
            i18n=deps.i18n,
            clock=deps.clock,
        ),
    )


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def make() -> SqlFeedbackUnitOfWork:
        return SqlFeedbackUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return make
