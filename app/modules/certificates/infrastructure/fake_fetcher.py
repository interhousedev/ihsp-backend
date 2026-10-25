"""Fake certificate downloads for ``EMIS__MODE=fake``: a one-page PDF, no network."""

from app.modules.certificates.ports.fetcher import FetchedFile

_FAKE_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


class FakeCertificateFetcher:
    """Returns the same small PDF for every URL."""

    async def fetch(self, url: str) -> FetchedFile:
        """Return the sample PDF named after the URL's last segment."""
        name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "certificate.pdf"
        return FetchedFile(name=name, data=_FAKE_PDF)
