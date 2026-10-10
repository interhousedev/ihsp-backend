"""Source modalities per model, the thin-source threshold and fake auto labels."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.ai.infrastructure.fake_structured import build_document
from app.modules.notebooks.application.generate_artifact import MIN_CONTENT_TOKENS
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.label_output import parse_labels
from app.modules.notebooks.domain.modality import readable_by, source_modality
from app.modules.notebooks.domain.prompts.labels import (
    LabelInput,
    labels_user_message,
    source_key,
)
from app.settings_ai import AiSettings, AiTaskSettings
from app.shared.ai_tasks import AiTask


def _source(kind: SourceKind, title: str, ref: dict[str, Any] | None = None) -> Source:
    now = datetime.now(UTC)
    return Source(
        id=uuid4(),
        notebook_id=uuid4(),
        owner_id=uuid4(),
        kind=kind,
        title=title,
        position=1,
        created_at=now,
        updated_at=now,
        ref=ref or {},
    )


def test_modalities_default_to_everything_and_a_task_can_narrow_them() -> None:
    task = AiTaskSettings.model_validate({"modalities": "text, pdf"})
    ai = AiSettings(tasks={AiTask.NOTEBOOK_CHAT: task})

    assert ai.profile(AiTask.STUDIO_QUIZ).modalities == (
        "text",
        "image",
        "audio",
        "video",
        "pdf",
    )
    assert ai.profile(AiTask.NOTEBOOK_CHAT).modalities == ("text", "pdf")


def test_the_modality_comes_from_the_content_type_format_or_name() -> None:
    assert source_modality(_source(SourceKind.TEXT, "Notes")) == "text"
    assert source_modality(_source(SourceKind.FILE, "scan.PNG")) == "image"
    audio = _source(SourceKind.FILE, "x", {"content_type": "audio/mpeg"})
    assert source_modality(audio) == "audio"
    book = _source(SourceKind.LIBRARY_ITEM, "Book", {"format": "pdf"})
    assert source_modality(book) == "pdf"
    epub = _source(SourceKind.LIBRARY_ITEM, "Book", {"format": "epub"})
    assert source_modality(epub) == "text"


def test_a_source_of_an_unsupported_kind_is_not_readable() -> None:
    video = _source(SourceKind.FILE, "lesson.mp4")

    assert not readable_by(video, ("text", "pdf"))
    assert readable_by(video, ("text", "video"))


def test_the_thin_source_threshold_is_about_one_sentence() -> None:
    assert MIN_CONTENT_TOKENS <= 10


def test_the_fake_model_labels_every_source_of_the_prompt() -> None:
    items = [LabelInput("Cells"), LabelInput("Derivatives"), LabelInput("Rome")]
    message = labels_user_message(items, [])

    data = build_document("nb_labels", [{"role": "user", "content": message}])
    parsed = parse_labels(data, {source_key(i): i for i in range(3)})  # type: ignore[arg-type]

    assert len(parsed.labels) == 3
    assert set(parsed.assignments) == {"s1", "s2", "s3"}
