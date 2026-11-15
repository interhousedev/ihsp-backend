"""Port of the shared directory between the API and the host migration runner."""

from typing import Protocol

from app.modules.admin.domain.migration import (
    MigrationState,
    RunnerRequest,
    RunnerStatus,
)


class MigrationStore(Protocol):
    """Small JSON files: the API owns state and requests, the runner the status."""

    def available(self) -> bool:
        """False when the deployment has no shared directory (migration is off)."""
        ...

    def read_state(self) -> MigrationState | None:
        """The API's state, or None when idle."""
        ...

    def write_state(self, state: MigrationState) -> None:
        """Replace the state atomically."""
        ...

    def clear_state(self) -> None:
        """Back to idle: forget the state, the runner's report and any request."""
        ...

    def read_status(self) -> RunnerStatus | None:
        """The runner's last report; None when absent or unreadable."""
        ...

    def queue_request(self, request: RunnerRequest) -> None:
        """Hand the request (with the pairing token, mode 0600) to the runner."""
        ...

    def withdraw_request(self) -> None:
        """Remove a request the runner has not picked up yet."""
        ...

    def queue_command(self, migration_id: str, action: str) -> None:
        """Ask the runner to ``cancel`` a running copy or ``resume`` the services."""
        ...
