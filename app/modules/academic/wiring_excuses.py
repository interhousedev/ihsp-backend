"""Builds the excuse services (requests, exclusions, decisions, thread, status)."""

from dataclasses import dataclass

from app.modules.academic.application.excuses.access import ExcuseAccess
from app.modules.academic.application.excuses.cancel_excuse import CancelExcuse
from app.modules.academic.application.excuses.coverage import ExcuseCoverageQuery
from app.modules.academic.application.excuses.create_exclusion import (
    CreateExcuseExclusion,
)
from app.modules.academic.application.excuses.create_request import (
    CreateExcuseRequest,
)
from app.modules.academic.application.excuses.decide_by_token import (
    DecideExcuseByToken,
)
from app.modules.academic.application.excuses.decide_excuse import DecideExcuse
from app.modules.academic.application.excuses.end_excuse import (
    EndExcuse,
    RevokeExcuse,
)
from app.modules.academic.application.excuses.excuse_status import ExcuseStatusQuery
from app.modules.academic.application.excuses.notices import ExcuseNotices
from app.modules.academic.application.excuses.post_message import PostExcuseMessage
from app.modules.academic.application.excuses.queries import (
    GetExcuse,
    ListExcuses,
    ListExcuseTemplates,
)
from app.modules.academic.application.excuses.views import ExcusePresenter
from app.modules.academic.application.excuses.work_offs import ExcuseWorkOffs
from app.modules.academic.infrastructure.excuses.directory import SqlExcuseDirectory
from app.modules.academic.infrastructure.excuses.file_usage import (
    SqlExcuseFileUsage,
)
from app.modules.academic.infrastructure.excuses.tokens import RedisDecisionTokens
from app.modules.academic.infrastructure.excuses.uow import SqlExcuseUnitOfWork
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class ExcuseServices:
    """Use cases (attribute name = file name) and the cross-module reader."""

    create_request: CreateExcuseRequest
    create_exclusion: CreateExcuseExclusion
    decide_excuse: DecideExcuse
    decide_by_token: DecideExcuseByToken
    cancel_excuse: CancelExcuse
    end_excuse: EndExcuse
    revoke_excuse: RevokeExcuse
    post_message: PostExcuseMessage
    list_excuses: ListExcuses
    get_excuse: GetExcuse
    list_templates: ListExcuseTemplates
    coverage: ExcuseCoverageQuery
    status: ExcuseStatusQuery
    file_usage: SqlExcuseFileUsage


def build_excuses(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    schedule: ScheduleQueries,
    files: FilesApi,
) -> ExcuseServices:
    """Wire the excuse use cases over the shared infrastructure."""
    clock = deps.clock

    def uow_factory() -> SqlExcuseUnitOfWork:
        return SqlExcuseUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    directory = SqlExcuseDirectory(deps.sessionmaker, schedule, identity)
    tokens = RedisDecisionTokens(deps.redis)
    access = ExcuseAccess(directory)
    notices = ExcuseNotices(directory=directory, tokens=tokens)
    presenter = ExcusePresenter(files=files, directory=directory)
    work_offs = ExcuseWorkOffs(
        schedule=schedule,
        text_for=lambda locale: deps.i18n.get_context(locale)("excuse-workoff-text"),
        clock=clock,
    )
    decide = DecideExcuse(
        uow_factory=uow_factory,
        clock=clock,
        directory=directory,
        access=access,
        notices=notices,
        work_offs=work_offs,
        tokens=tokens,
        presenter=presenter,
    )
    return ExcuseServices(
        create_request=CreateExcuseRequest(
            uow_factory=uow_factory,
            clock=clock,
            directory=directory,
            files=files,
            notices=notices,
            presenter=presenter,
        ),
        create_exclusion=CreateExcuseExclusion(
            uow_factory=uow_factory,
            clock=clock,
            directory=directory,
            access=access,
            notices=notices,
            work_offs=work_offs,
            presenter=presenter,
        ),
        decide_excuse=decide,
        decide_by_token=DecideExcuseByToken(tokens=tokens, decide=decide),
        cancel_excuse=CancelExcuse(
            uow_factory=uow_factory,
            clock=clock,
            access=access,
            tokens=tokens,
            presenter=presenter,
        ),
        end_excuse=EndExcuse(
            uow_factory=uow_factory, clock=clock, access=access, presenter=presenter
        ),
        revoke_excuse=RevokeExcuse(
            uow_factory=uow_factory,
            clock=clock,
            access=access,
            notices=notices,
            presenter=presenter,
        ),
        post_message=PostExcuseMessage(
            uow_factory=uow_factory,
            clock=clock,
            directory=directory,
            access=access,
            files=files,
            notices=notices,
            presenter=presenter,
        ),
        list_excuses=ListExcuses(
            uow_factory=uow_factory, directory=directory, presenter=presenter
        ),
        get_excuse=GetExcuse(
            uow_factory=uow_factory, access=access, presenter=presenter
        ),
        list_templates=ListExcuseTemplates(uow_factory=uow_factory),
        coverage=ExcuseCoverageQuery(uow_factory=uow_factory),
        status=ExcuseStatusQuery(
            uow_factory=uow_factory, directory=directory, schedule=schedule
        ),
        file_usage=SqlExcuseFileUsage(deps.sessionmaker),
    )
