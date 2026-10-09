"""Failures of the UniLibrary source, as the client and the breaker see them."""

from typing import Literal

UpstreamKind = Literal[
    "timeout",  # no answer in time
    "network",  # connection refused, reset, DNS
    "forbidden",  # 403: counts like any failure and is never worked around
    "rate_limited",  # 429 or `Retry-After`
    "server",  # 5xx
    "bad_status",  # any other unexpected status
    "bad_payload",  # 200 with a body we cannot read
    "busy",  # our own request budget stayed full
]


class UpstreamError(Exception):
    """UniLibrary did not give a usable answer.

    `retry_after` is the number of seconds the source asked us to wait (header
    `Retry-After`); the breaker honours it.
    """

    def __init__(
        self,
        kind: UpstreamKind,
        *,
        status: int | None = None,
        retry_after: int | None = None,
        detail: str = "",
    ) -> None:
        """Remember what went wrong; nothing here is shown to a user."""
        super().__init__(f"{kind} {status or ''} {detail}".strip())
        self.kind: UpstreamKind = kind
        self.status = status
        self.retry_after = retry_after
        self.detail = detail
