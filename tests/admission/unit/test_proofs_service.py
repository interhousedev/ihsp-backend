"""Proof links: validation, reachability check, ownership."""

from typing import Any

from app.modules.admission.application.proofs import _FetchFailed
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    InvalidProofUrlError,
    ProofSourceError,
)
from app.modules.admission.domain.help_proofs import detect_url_kind, validate_proof_url
from app.shared.safe_fetch import FetchedBody
from tests.admission.unit.proofs_kit import OTHER, ProofKit

import pytest


class Fetcher:
    """Answers with a fixed page or fails."""

    def __init__(self, fail: bool = False) -> None:
        """Choose the outcome."""
        self.fail = fail
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedBody:
        self.calls.append(url)
        if self.fail:
            raise _FetchFailed()
        return FetchedBody(
            url, "x.org", "/", "text/html", b"<html><title> My  site </title>"
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost/x",
        "https://10.0.0.1/x",
        "https://[::1]/x",
        "https://example.com:8443/",
        "https://u:p@example.com/",
        "https://printer.local/",
        "https://intranet/",
        "",
    ],
)
def test_unsafe_urls_rejected(url: str) -> None:
    with pytest.raises(InvalidProofUrlError):
        validate_proof_url(url)


def test_kind_detection() -> None:
    assert detect_url_kind("https://www.linkedin.com/in/a") == "linkedin"
    assert detect_url_kind("https://t.me/a") == "telegram"
    assert detect_url_kind("https://example.com") == "website"


async def test_url_checked_with_title() -> None:
    f: Any = Fetcher()
    k = ProofKit(f)
    res = await k.proofs.add(await k.ctx(), k.item, url="https://example.com/a")
    assert res.proof.status == "checked" and res.title == "My site"
    assert [p.status for p in await k.proofs.list(await k.ctx(), k.item)] == ["checked"]


async def test_failed_and_linkedin_never_checked() -> None:
    k = ProofKit(Fetcher(fail=True))
    ctx = await k.ctx()
    bad = await k.proofs.add(ctx, k.item, url="https://example.com/a")
    assert bad.proof.status == "failed"
    li = await k.proofs.add(ctx, k.item, url="https://linkedin.com/in/a")
    assert li.proof.status == "unverifiable"


async def test_text_proof_unverifiable_and_source_exactly_one() -> None:
    k = ProofKit(Fetcher())
    ctx = await k.ctx()
    res = await k.proofs.add(ctx, k.item, pasted_text="I did it")
    assert res.proof.status == "unverifiable"
    with pytest.raises(ProofSourceError):
        await k.proofs.add(ctx, k.item, url="https://a.org", pasted_text="x")


async def test_stranger_cannot_touch_item() -> None:
    k = ProofKit(Fetcher())
    other = await k.ctx(OTHER)
    with pytest.raises(AdmissionNotFoundError):
        await k.proofs.add(other, k.item, pasted_text="x")
    with pytest.raises(AdmissionNotFoundError):
        await k.proofs.list(other, k.item)
