"""Builds the legal module (container.legal)."""

from dataclasses import dataclass

from app.modules.legal.application.accept import AcceptDocuments
from app.modules.legal.application.drafts import PublishDraft, SaveDraft
from app.modules.legal.application.forget import ForgetScope
from app.modules.legal.application.queries import (
    CountAcceptances,
    GetCurrentDocument,
    ListAllDocuments,
    ListCurrentDocuments,
    ListOverview,
    ListPending,
    RequireConsent,
)
from app.modules.legal.infrastructure.consent import write_acceptances
from app.modules.legal.infrastructure.uow import SqlLegalUnitOfWork
from app.modules.legal.ports.unit_of_work import UowFactory
from app.shared.contracts.legal import LegalHooks
from app.shared.wiring import ModuleDeps


class CurrentVersions:
    """Read side of registration consent: the current version of each kind."""

    def __init__(self, list_current: ListCurrentDocuments) -> None:
        """Wrap the query."""
        self._list_current = list_current

    async def current_versions(self) -> dict[str, int]:
        """The current published version of every global kind that has one."""
        return {d.kind: d.version for d in await self._list_current.execute()}


@dataclass(slots=True)
class LegalServices:
    """Use cases of the legal module and the hooks identity registers with."""

    list_current: ListCurrentDocuments
    get_current: GetCurrentDocument
    pending: ListPending
    require_consent: RequireConsent
    accept: AcceptDocuments
    list_all: ListAllDocuments
    save_draft: SaveDraft
    publish: PublishDraft
    count_acceptances: CountAcceptances
    overview: ListOverview
    forget_scope: ForgetScope
    hooks: LegalHooks


@dataclass(frozen=True, slots=True)
class LegalOverrides:
    """Replacement for the SQL unit of work (for tests)."""

    uow_factory: UowFactory | None = None


def build(deps: ModuleDeps, overrides: LegalOverrides | None = None) -> LegalServices:
    """Wire the module."""
    over = overrides or LegalOverrides()
    uow_factory = over.uow_factory or _sql_uow_factory(deps)
    list_current = ListCurrentDocuments(uow_factory=uow_factory)
    require_consent = RequireConsent(uow_factory=uow_factory)
    return LegalServices(
        list_current=list_current,
        get_current=GetCurrentDocument(uow_factory=uow_factory),
        pending=ListPending(uow_factory=uow_factory),
        require_consent=require_consent,
        accept=AcceptDocuments(uow_factory=uow_factory, clock=deps.clock),
        list_all=ListAllDocuments(uow_factory=uow_factory),
        save_draft=SaveDraft(uow_factory=uow_factory, clock=deps.clock),
        publish=PublishDraft(
            uow_factory=uow_factory,
            clock=deps.clock,
            on_published=require_consent.forget_all,
        ),
        count_acceptances=CountAcceptances(uow_factory=uow_factory),
        overview=ListOverview(uow_factory=uow_factory),
        forget_scope=ForgetScope(
            uow_factory=uow_factory, require_consent=require_consent
        ),
        hooks=LegalHooks(
            consent=CurrentVersions(list_current), writer=write_acceptances
        ),
    )


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def factory() -> SqlLegalUnitOfWork:
        return SqlLegalUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return factory
