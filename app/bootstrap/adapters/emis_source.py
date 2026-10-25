"""Choice of the EmisSource: the identity gateway in process, or over HTTP."""

from collections.abc import Awaitable, Callable

from app.bootstrap.adapters.http_emis_source import HttpEmisSource
from app.settings import Settings
from app.shared.contracts.emis import EmisSource

Closer = Callable[[], Awaitable[None]]


def make_emis_source(
    settings: Settings, *, gateway: EmisSource | None, in_process: bool
) -> tuple[EmisSource, Closer | None]:
    """Return the in-process gateway (processes `all`, `identity`) or HttpEmisSource.

    `HttpEmisSource` calls `/internal/emis/*` of the identity process with the
    service token (processes `api`, `bot`, `worker`); it never sees Vault.
    """
    if in_process:
        if gateway is None:
            raise ValueError("the in-process EMIS source needs the identity EMIS part")
        return gateway, None
    source = HttpEmisSource.from_settings(settings)
    return source, source.aclose
