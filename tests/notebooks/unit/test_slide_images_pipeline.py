"""Slide pictures: the pipeline stages, the fallback and the pptx export."""

import io
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.bot.assistant.artifact_notice import artifact_file
from app.modules.notebooks.application.export.pptx import slides_to_pptx
from app.modules.notebooks.application.slide_images import sign_images
from app.modules.notebooks.application.slide_pipeline import (
    STAGE_DESIGN,
    STAGE_IMAGES,
    STAGE_RESEARCH,
    SlidePipeline,
)
from app.modules.notebooks.domain.artifacts.kinds.slides import resolve_images
from app.modules.notebooks.domain.artifacts.slide_outline import PlanSlide
from app.modules.notebooks.infrastructure.fake_images import (
    PNG_1X1,
    FakeImageFetcher,
    FakeImageSearch,
)
from app.settings import NotebooksSettings
from app.shared.contracts.files import FilePurpose, FileScope

from pptx import Presentation
from uuid_utils.compat import uuid7


class _Files:
    """Keeps the stored bytes and the scope they were stored under."""

    def __init__(self) -> None:
        self.stored: dict[UUID, tuple[FileScope, bytes]] = {}

    async def store_bytes(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        data: bytes,
    ) -> Any:
        file_id = uuid7()
        self.stored[file_id] = (scope, data)
        return SimpleNamespace(id=file_id)


def _pipeline(files: _Files, **cfg: Any) -> SlidePipeline:
    settings = SimpleNamespace(notebooks=NotebooksSettings(**cfg))
    return SlidePipeline(
        web_search=None,
        images=FakeImageSearch(),
        fetcher=FakeImageFetcher(),  # type: ignore[arg-type]
        files=files,  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
    )


async def test_pipeline_reports_stages_and_labels_the_images() -> None:
    files = _Files()
    stages: list[str] = []

    async def on_stage(stage: str) -> None:
        stages.append(stage)

    result = await _pipeline(files, slides_images_per_slide=1).run(
        user_id=uuid7(),
        outline=[PlanSlide(title="Volcanoes"), PlanSlide(title="Rivers")],
        locale="en",
        on_stage=on_stage,
    )

    assert stages == [STAGE_IMAGES, STAGE_DESIGN]  # no web search: no research
    assert STAGE_RESEARCH not in stages
    assert list(result.images) == ["I1", "I2"]
    assert "I1 (for slide 1, Volcanoes)" in result.images_block
    assert all(scope is FileScope.SYSTEM for scope, _ in files.stored.values())
    assert {data for _, data in files.stored.values()} == {PNG_1X1}


async def test_pipeline_without_images_skips_the_stage() -> None:
    stages: list[str] = []

    async def on_stage(stage: str) -> None:
        stages.append(stage)

    result = await _pipeline(_Files(), slides_images_per_slide=0).run(
        user_id=uuid7(),
        outline=[PlanSlide(title="Volcanoes")],
        locale="en",
        on_stage=on_stage,
    )

    assert stages == [STAGE_DESIGN]
    assert result.images == {}
    assert result.images_block == ""


def test_image_layout_without_a_picture_falls_back() -> None:
    slides = [
        {"layout": "image_left", "title": "A", "bullets": ["x"]},
        {"layout": "full_image", "title": "B"},
        {"layout": "image_right", "title": "C", "image_id": "I9", "bullets": ["y"]},
    ]
    out = resolve_images(slides, {})

    assert [s["layout"] for s in out] == ["bullets", "section", "bullets"]
    assert all("image_id" not in s for s in out)


def test_image_layout_with_a_known_label_gets_the_image() -> None:
    image = {"file_id": "f1", "alt": "a", "attribution": "Me, CC0"}
    out = resolve_images(
        [{"layout": "image_left", "title": "A", "image_id": "I1", "bullets": ["x"]}],
        {"I1": image},
    )

    assert out[0]["layout"] == "image_left"
    assert out[0]["image"] == image


def _deck(layout: str, **fields: Any) -> list[dict[str, Any]]:
    return [{"layout": layout, "title": "T", "notes": "say it", **fields}]


def _open(data: bytes) -> Any:
    return Presentation(io.BytesIO(data))


def _pictures(presentation: Any) -> list[Any]:
    return [
        shape
        for slide in presentation.slides
        for shape in slide.shapes
        if shape.shape_type == 13
    ]


def test_pptx_places_the_picture_and_credits_it() -> None:
    image = {
        "file_id": "f1",
        "alt": "A volcano",
        "attribution": "Ann, CC BY 4.0",
        "source_url": "https://commons.example/f1",
    }
    for layout in ("image_left", "image_right", "full_image"):
        data = slides_to_pptx(
            "Deck", None, _deck(layout, image=image, bullets=["a"]), {"f1": PNG_1X1}
        )
        presentation = _open(data)
        assert len(_pictures(presentation)) == 1
        slide = presentation.slides[1]
        notes = slide.notes_slide.notes_text_frame.text
        assert "say it" in notes and "Ann, CC BY 4.0" in notes
        texts = " ".join(s.text_frame.text for s in slide.shapes if s.has_text_frame)
        assert "Ann, CC BY 4.0" in texts


def test_pptx_without_the_picture_bytes_is_text_only() -> None:
    image = {"file_id": "gone", "alt": "x", "attribution": "Ann"}
    data = slides_to_pptx("Deck", None, _deck("image_left", image=image, bullets=["a"]))

    presentation = _open(data)
    assert _pictures(presentation) == []
    assert "Ann" not in presentation.slides[1].notes_slide.notes_text_frame.text


def test_pptx_stats_timeline_and_comparison() -> None:
    slides = [
        {
            "layout": "stats",
            "title": "Numbers",
            "stats": [{"value": "72%", "label": "pass"}, {"value": "9", "label": "n"}],
        },
        {
            "layout": "timeline",
            "title": "History",
            "timeline": [{"label": "1990", "text": "Start"}],
        },
        {
            "layout": "comparison",
            "title": "Versus",
            "left": {"heading": "Cats", "bullets": ["purr"]},
            "right": {"heading": "Dogs", "bullets": ["bark"]},
        },
    ]
    presentation = _open(slides_to_pptx("Deck", None, slides))

    def words(index: int) -> str:
        shapes = presentation.slides[index].shapes
        return " ".join(s.text_frame.text for s in shapes if s.has_text_frame)

    assert "72%" in words(1) and "pass" in words(1)
    assert "1990" in words(2) and "Start" in words(2)
    assert "Cats" in words(3) and "bark" in words(3)


class _Signer:
    async def download_url(self, file_id: UUID, **kwargs: Any) -> str:
        return f"https://files.test/{file_id}"


async def test_sign_images_adds_a_url_and_keeps_the_input() -> None:
    file_id = str(uuid7())
    content = {"slides": [{"layout": "image_left", "image": {"file_id": file_id}}]}

    signed = await sign_images(_Signer(), content)  # type: ignore[arg-type]

    assert signed is not None
    assert signed["slides"][0]["image"]["url"] == f"https://files.test/{file_id}"
    assert "url" not in content["slides"][0]["image"]


class _Notebooks:
    def __init__(self, found: dict[str, Any]) -> None:
        self.found = found

    async def get_artifact_content(self, *args: Any) -> dict[str, Any]:
        return self.found


async def test_bot_deck_file_carries_the_pictures() -> None:
    image = {"file_id": "f1", "alt": "A", "attribution": "Ann, CC0"}
    found = {
        "kind": "slides",
        "title": "Deck",
        "content": {"slides": _deck("image_left", image=image, bullets=["a"])},
        "images": {"f1": PNG_1X1},
    }
    payload = {"notebook_id": str(uuid7()), "artifact_id": str(uuid7())}

    attached = await artifact_file(_Notebooks(found), uuid7(), payload)

    assert attached is not None
    assert len(_pictures(_open(attached[1]))) == 1
