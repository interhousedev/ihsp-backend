"""LIB-12 / D3: the integration is link-only; it can never fetch a file."""

import inspect
import re
from pathlib import Path

from app.modules.library.infrastructure import unilibrary
from app.modules.library.infrastructure.unilibrary.catalog import CachedCatalog
from app.modules.library.infrastructure.unilibrary.client import UniLibraryClient
from app.modules.library.ports.external_catalog import ExternalCatalog

PACKAGE = Path(inspect.getfile(unilibrary)).parent
FORBIDDEN_WORDS = ("download", "storage", "file", "media", "attachment", "stream")


def _sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.glob("*.py"))
    }


def test_the_client_and_the_port_have_no_file_method() -> None:
    """LIB-12: no public method names a file, a download or a storage path."""
    for cls in (UniLibraryClient, CachedCatalog, ExternalCatalog):
        public = [name for name in dir(cls) if not name.startswith("_")]
        offending = [
            name for name in public if any(word in name for word in FORBIDDEN_WORDS)
        ]
        assert offending == [], f"{cls.__name__}: {offending}"


def test_the_package_builds_no_storage_or_download_url() -> None:
    """LIB-12: no `/storage`, no `/{id}/{filename}/{ext}`, no file fields."""
    for name, source in _sources().items():
        code = re.sub(r'""".*?"""|#.*', "", source, flags=re.S)
        for word in ("/storage", "filename", "publisher_resource_file", "download"):
            assert word not in code, f"{name} mentions {word}"


def test_the_only_paths_are_the_documented_metadata_endpoints() -> None:
    """LIB-12: list with media, one record, and the taxonomy lists."""
    client_source = _sources()["client.py"]

    paths = set(re.findall(r'"(/api/[^"]*)"', client_source))

    assert paths == {
        "/api/user/guest-publisher-resources-with-media",
        "/api/user/guest-publisher-resources",
        "/api/crm/{name}/lists",
    }
