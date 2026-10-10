"""Builds the dashboard module services (container.dashboard)."""

from dataclasses import dataclass

from app.modules.dashboard.application.get_layout import GetLayout
from app.modules.dashboard.application.save_layout import SaveLayout
from app.modules.dashboard.infrastructure.uow import SqlDashboardUnitOfWork
from app.modules.dashboard.ports.unit_of_work import UowFactory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class DashboardOverrides:
    """Test doubles; None keeps the real adapter."""

    uow_factory: UowFactory | None = None


@dataclass(slots=True)
class DashboardServices:
    """Use cases of the dashboard module."""

    get_layout: GetLayout
    save_layout: SaveLayout


def build(
    deps: ModuleDeps, overrides: DashboardOverrides | None = None
) -> DashboardServices:
    """Wire the module."""
    over = overrides or DashboardOverrides()
    uow_factory = over.uow_factory or _sql_uow_factory(deps)
    return DashboardServices(
        get_layout=GetLayout(uow_factory=uow_factory),
        save_layout=SaveLayout(uow_factory=uow_factory),
    )


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def make() -> SqlDashboardUnitOfWork:
        return SqlDashboardUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return make
