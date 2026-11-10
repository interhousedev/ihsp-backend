"""SQL unit of work of the faces module."""

from app.modules.faces.infrastructure.repositories.sql import (
    SqlActivityRepository,
    SqlDeviceRepository,
    SqlProfileRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlFacesUnitOfWork(SqlUnitOfWork):
    """One transaction over profiles, devices and their activity."""

    profiles: SqlProfileRepository
    devices: SqlDeviceRepository
    activity: SqlActivityRepository

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.profiles = SqlProfileRepository(self.session)
        self.devices = SqlDeviceRepository(self.session)
        self.activity = SqlActivityRepository(self.session)
