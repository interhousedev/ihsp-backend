"""Where finished cartridge imports keep their result for the uploader."""

from typing import Any, Protocol


class CartridgeImportResults(Protocol):
    """The result of an import job (course id, report or error), kept for a day."""

    async def save(self, job_id: str, result: dict[str, Any]) -> None:
        """Store the result of the job."""
        ...

    async def get(self, job_id: str) -> dict[str, Any] | None:
        """Return the result, or None while running or after it expired."""
        ...
