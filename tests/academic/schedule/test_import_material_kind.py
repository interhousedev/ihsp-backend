"""B2: an EMIS material keeps its kind (homework, classwork, video)."""

from typing import Any
from uuid import uuid4

from app.modules.academic.application.schedule.import_materials import (
    ImportLessonMaterials,
)
from app.modules.academic.application.schedule.ports.lesson_urls import EmisMaterial
from app.shared.contracts.emis import EmisFile


class Emis:
    async def download(self, user_id: Any, url: str, *, max_bytes: int) -> EmisFile:
        return EmisFile(name="a.pdf", content_type="application/pdf", data=url.encode())


class Files:
    async def find_by_content(self, **_: Any) -> None:
        return None

    async def store_bytes(self, **_: Any) -> Any:
        return type("Ref", (), {"id": uuid4()})()


class Links:
    def __init__(self) -> None:
        self.files: list[Any] = []
        self.urls: list[Any] = []

    async def emis_sources(self, lesson_ids: Any) -> set[Any]:
        return set()

    async def import_lesson_files(self, files: Any) -> int:
        self.files.extend(files)
        return len(files)

    async def import_lesson_urls(self, urls: Any) -> int:
        self.urls.extend(urls)
        return len(urls)


async def test_the_kind_reaches_the_links_module() -> None:
    """B2: files and links carry the kind EMIS gave them."""
    links = Links()
    use_case = ImportLessonMaterials(
        emis=Emis(),  # type: ignore[arg-type]
        files=Files(),  # type: ignore[arg-type]
        links=links,  # type: ignore[arg-type]
        max_bytes=1000,
    )
    lesson = uuid4()

    await use_case.import_materials(
        uuid4(),
        [
            EmisMaterial(lesson, "https://e/h.pdf", "T", "homework"),
            EmisMaterial(lesson, "https://e/c.pdf", "T", "classwork"),
            EmisMaterial(lesson, "https://e/v", "T", "video"),
        ],
    )

    assert {f.source_url: f.kind for f in links.files} == {
        "https://e/h.pdf": "homework",
        "https://e/c.pdf": "classwork",
    }
    assert [(u.url, u.kind) for u in links.urls] == [("https://e/v", "video")]
