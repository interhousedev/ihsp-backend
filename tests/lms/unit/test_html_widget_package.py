"""HTML widget packages: what is accepted, what is refused, and how long links live."""

import io
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.lms.application.h5p_links import H5PLinks
from app.modules.lms.application.html_widget_links import (
    HtmlWidgetLinks,
    WidgetFileNotFound,
)
from app.modules.lms.domain.h5p_token import package_prefix
from app.modules.lms.domain.html_widget import (
    WidgetPackageError,
    parse_widget,
    widget_content_type,
    widget_prefix,
)
from app.modules.lms.infrastructure.h5p_memory_store import MemoryH5PStore

import pytest

LIMITS = {"max_bytes": 10_000, "max_unpacked": 20_000, "max_files": 5}


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _reason(data: bytes, filename: str = "w.zip") -> str:
    with pytest.raises(WidgetPackageError) as caught:
        parse_widget(data, filename, **LIMITS)
    return caught.value.reason


def test_a_single_html_file_becomes_the_entry() -> None:
    package = parse_widget(b"<p>hi</p>", "Quiz.HTML", **LIMITS)
    assert [entry.path for entry in package.entries] == ["index.html"]


def test_a_zip_keeps_its_files_and_skips_mac_junk() -> None:
    data = _zip(
        {
            "index.html": b"<p>",
            "js/app.js": b"1",
            "__MACOSX/._index.html": b"x",
            ".DS_Store": b"x",
        }
    )
    package = parse_widget(data, "w.zip", **LIMITS)
    assert sorted(entry.path for entry in package.entries) == [
        "index.html",
        "js/app.js",
    ]


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({"../evil.html": b"x", "index.html": b"x"}, "unsafe-path"),
        ({"/etc/passwd.html": b"x", "index.html": b"x"}, "unsafe-path"),
        ({"a/../../x.js": b"x", "index.html": b"x"}, "unsafe-path"),
        ({"index.html": b"x", "run.exe": b"x"}, "file-type"),
        ({"index.html": b"x", "page.php": b"x"}, "file-type"),
        ({"sub/index.html": b"x"}, "no-index"),
        ({f"{n}.js": b"x" for n in range(5)} | {"index.html": b"x"}, "too-many-files"),
        ({"index.html": b"x", "big.js": b"0" * 25_000}, "too-large"),
    ],
)
def test_bad_zips_are_refused(files: dict[str, bytes], reason: str) -> None:
    assert _reason(_zip(files)) == reason


def test_uploads_over_the_cap_and_odd_types_are_refused() -> None:
    assert _reason(b"0" * 10_001, "w.html") == "too-large"
    assert _reason(b"MZ", "w.exe") == "file-type"
    assert _reason(b"not a zip", "w.zip") == "not-zip"


def test_types_are_explicit_and_svg_is_an_image() -> None:
    assert widget_content_type("a/b.svg") == "image/svg+xml"
    assert (widget_content_type("index.html") or "").startswith("text/html")
    assert widget_content_type("x.php") is None


async def test_links_expire_and_tokens_do_not_cross_over() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock = type("C", (), {"now": lambda self: now})()
    store = MemoryH5PStore()
    course, package = uuid4(), uuid4()
    await store.put(widget_prefix(course, package) + "index.html", b"<p>", "text/html")
    await store.put(package_prefix(course, package) + "index.html", b"<p>", "text/html")
    links = HtmlWidgetLinks(b"widget-key", clock, store)
    token = links.launch(course, package).entry_url.split("/")[-2]

    assert (await links.read(token, "index.html")).data == b"<p>"
    with pytest.raises(WidgetFileNotFound):
        await links.read(token, "../index.html")

    h5p = H5PLinks(b"h5p-key", clock, store).launch(course, package)
    with pytest.raises(WidgetFileNotFound):
        await links.read(h5p.base_url.rstrip("/").split("/")[-1], "index.html")

    now = now + timedelta(hours=2)
    with pytest.raises(WidgetFileNotFound):
        await links.read(token, "index.html")
