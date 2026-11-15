"""File store of the migration: JSON files in the directory shared with the runner.

``state.json`` is written by the API only. ``status.json`` is written by the host runner
only. ``request.json`` (mode 0600, the one-time pairing token) and ``command.json``
are written here and consumed (deleted) by the runner. Writes are atomic renames.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.modules.admin.domain.migration import (
    MigrationPhase,
    MigrationState,
    RunnerRequest,
    RunnerStatus,
)

STATE = "state.json"
STATUS = "status.json"
REQUEST = "request.json"
COMMAND = "command.json"


class FileMigrationStore:
    """``MigrationStore`` over a directory (``/migration`` in the api container)."""

    def __init__(self, directory: Path | None) -> None:
        """An empty setting means migration is off."""
        self.directory = directory

    def available(self) -> bool:
        """The directory exists."""
        return self.directory is not None and self.directory.is_dir()

    def read_state(self) -> MigrationState | None:
        """Load ``state.json``."""
        data = self._read(STATE)
        if data is None:
            return None
        try:
            return MigrationState(
                id=data["id"],
                phase=MigrationPhase(data["phase"]),
                target_host=data["target_host"],
                target_port=int(data["target_port"]),
                target_url=data.get("target_url"),
                requested_by=data["requested_by"],
                requested_at=datetime.fromisoformat(data["requested_at"]),
                updated_at=datetime.fromisoformat(data["updated_at"]),
                step=data.get("step"),
                steps_done=tuple(data.get("steps_done", ())),
                error=data.get("error"),
                dry_run=bool(data.get("dry_run", False)),
            )
        except (KeyError, ValueError, TypeError):
            return None

    def write_state(self, state: MigrationState) -> None:
        """Save ``state.json``."""
        self._write(
            STATE,
            {
                "id": state.id,
                "phase": state.phase.value,
                "target_host": state.target_host,
                "target_port": state.target_port,
                "target_url": state.target_url,
                "requested_by": state.requested_by,
                "requested_at": state.requested_at.isoformat(),
                "updated_at": state.updated_at.isoformat(),
                "step": state.step,
                "steps_done": list(state.steps_done),
                "error": state.error,
                "dry_run": state.dry_run,
            },
        )

    def clear_state(self) -> None:
        """Delete the state, the report and the unconsumed request and command."""
        for name in (STATE, STATUS, REQUEST, COMMAND):
            self._remove(name)

    def read_status(self) -> RunnerStatus | None:
        """Load ``status.json`` of the runner."""
        data = self._read(STATUS)
        if data is None:
            return None
        try:
            return RunnerStatus(
                id=str(data["id"]),
                state=str(data["state"]),
                step=data.get("step"),
                steps_done=tuple(data.get("steps_done", ())),
                error=data.get("error"),
                updated_at=datetime.fromisoformat(data["updated_at"]),
                dry_run=bool(data.get("dry_run", False)),
            )
        except (KeyError, ValueError, TypeError):
            return None

    def queue_request(self, request: RunnerRequest) -> None:
        """Write ``request.json`` (the runner deletes it once it has read it)."""
        self._write(
            REQUEST,
            {
                "id": request.id,
                "target_host": request.target_host,
                "target_port": request.target_port,
                "pairing_token": request.pairing_token,
                "requested_at": request.requested_at.isoformat(),
                "dry_run": request.dry_run,
            },
        )

    def withdraw_request(self) -> None:
        """Delete ``request.json`` if the runner has not taken it."""
        self._remove(REQUEST)

    def queue_command(self, migration_id: str, action: str) -> None:
        """Write ``command.json``."""
        self._write(COMMAND, {"id": migration_id, "action": action})

    # -- file helpers -------------------------------------------------------------

    def _path(self, name: str) -> Path:
        if self.directory is None:
            raise RuntimeError("migration directory is not configured")
        return self.directory / name

    def _read(self, name: str) -> dict[str, Any] | None:
        if not self.available():
            return None
        try:
            data = json.loads(self._path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, name: str, data: dict[str, Any]) -> None:
        target = self._path(name)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _remove(self, name: str) -> None:
        if self.available():
            self._path(name).unlink(missing_ok=True)
