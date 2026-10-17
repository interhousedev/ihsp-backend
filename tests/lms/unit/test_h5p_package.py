"""H5P packages: validation, signed links and serving the stored files."""

import io
import json
import zipfile
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.lms.application.h5p_links import H5PFileNotFound, H5PLinks
from app.modules.lms.domain.h5p_package import H5PPackageError, parse_package
from app.modules.lms.domain.h5p_token import package_prefix, sign_token, verify_token
from app.modules.lms.infrastructure.h5p_memory_store import MemoryH5PStore

import pytest

MANIFEST = {"title": "Quiz", "mainLibrary": "H5P.QuestionSet", "language": "en"}


def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def package(**extra: bytes) -> dict[str, bytes]:
    return {
        "h5p.json": json.dumps(MANIFEST).encode(),
        "content/content.json": b"{}",
        "H5P.QuestionSet-1.20/library.json": b"{}",
        "H5P.QuestionSet-1.20/js/questionset.js": b"var a;",
        **extra,
    }


class FixedClock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


def test_a_valid_package_is_unpacked_with_types() -> None:
    parsed = parse_package(make_zip(package(**{"__MACOSX/._x": b"junk"})))

    assert parsed.title == "Quiz"
    assert parsed.main_library == "H5P.QuestionSet"
    types = {entry.path: entry.content_type for entry in parsed.entries}
    assert types["H5P.QuestionSet-1.20/js/questionset.js"] == "text/javascript"
    assert "__MACOSX/._x" not in types


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({"content/content.json": b"{}"}, "no-h5p-json"),
        ({"h5p.json": json.dumps(MANIFEST).encode()}, "no-content-json"),
        (package(**{"../evil.js": b"x"}), "unsafe-path"),
        (package(**{"content/../../evil.js": b"x"}), "unsafe-path"),
        (package(**{"/etc/passwd.txt": b"x"}), "unsafe-path"),
        (package(**{"content/run.exe": b"MZ"}), "file-type"),
        (package(**{"content/page.html": b"<script>"}), "file-type"),
        (package(**{"content/Makefile": b"x"}), "file-type"),
        (
            {"h5p.json": b'{"title": 1}', "content/content.json": b"{}"},
            "bad-h5p-json",
        ),
    ],
)
def test_bad_packages_are_rejected(files: dict[str, bytes], reason: str) -> None:
    with pytest.raises(H5PPackageError) as caught:
        parse_package(make_zip(files))
    assert caught.value.reason == reason


def test_a_non_zip_is_rejected() -> None:
    with pytest.raises(H5PPackageError) as caught:
        parse_package(b"not a zip at all")
    assert caught.value.reason == "not-zip"


def test_an_oversize_upload_is_rejected_before_unpacking() -> None:
    with pytest.raises(H5PPackageError) as caught:
        parse_package(make_zip(package()), max_bytes=10)
    assert caught.value.reason == "too-large"


def test_too_much_unpacked_data_is_rejected() -> None:
    big = package(**{"content/big.json": b"0" * 10_000})
    with pytest.raises(H5PPackageError) as caught:
        parse_package(make_zip(big), max_unpacked=5_000)
    assert caught.value.reason == "too-large"


def test_tokens_expire_and_cannot_be_tampered_with() -> None:
    course, pkg = uuid4(), uuid4()
    token = sign_token(b"k", course, pkg, expires=1000)

    claims = verify_token(b"k", token, now=999)
    assert claims is not None and claims.package_id == pkg
    assert verify_token(b"k", token, now=1000) is None
    assert verify_token(b"other", token, now=0) is None
    other = sign_token(b"k", course, uuid4(), expires=1000)
    forged = ".".join(other.split(".")[:3] + token.split(".")[3:])
    assert verify_token(b"k", forged, now=0) is None


async def test_links_serve_stored_files_only_with_a_valid_token() -> None:
    store = MemoryH5PStore()
    course, pkg = uuid4(), uuid4()
    await store.put(package_prefix(course, pkg) + "h5p.json", b"{}", "application/json")
    clock = FixedClock(datetime(2026, 10, 1, tzinfo=UTC))
    links = H5PLinks(b"key", clock, store)

    launch = links.launch(course, pkg)
    token = launch.base_url.removeprefix("/v1/lms/h5p/").strip("/")
    file = await links.read(token, "h5p.json")

    assert launch.base_url.startswith("/v1/lms/h5p/")
    assert file.data == b"{}" and file.content_type == "application/json"
    for path in ("missing.json", "../h5p.json", "content/x.exe"):
        with pytest.raises(H5PFileNotFound):
            await links.read(token, path)
    with pytest.raises(H5PFileNotFound):
        await links.read(token[:-2] + "xx", "h5p.json")
    clock.at = datetime(2026, 10, 2, tzinfo=UTC)
    with pytest.raises(H5PFileNotFound):
        await links.read(token, "h5p.json")
