"""Caption tracks of video blocks: schema rules, referenced files and the purpose."""

from typing import Any
from uuid import UUID, uuid4

from app.modules.lms.application.authoring.draft_writer import StepDraftWriter
from app.modules.lms.domain.authoring.content_edit import (
    caption_file_ids,
    extract_file_ids,
)
from app.modules.lms.domain.authoring.errors import ContentInvalidError
from app.modules.lms.domain.step_content import CaptionTrack, StepContent, VideoBlock
from app.modules.lms.domain.student_render import render_step
from app.shared.contracts.files import FilePurpose, FileRef, FileScope

import pytest
from pydantic import ValidationError

UZ = str(uuid4())
RU = str(uuid4())


def _track(lang: str, file_id: str, *, default: bool = False) -> dict[str, Any]:
    return {"lang": lang, "label": lang.upper(), "file_id": file_id, "default": default}


def _ref(file_id: str, purpose: FilePurpose) -> FileRef:
    return FileRef(
        id=UUID(file_id),
        owner_id=uuid4(),
        scope=FileScope.STAFF,
        purpose=purpose,
        name="uz.vtt",
        content_type="text/vtt",
        byte_size=10,
        status="ready",
        text_bytes=None,
    )


class _Files:
    """Only `get_many` of the files API."""

    def __init__(self, *refs: FileRef) -> None:
        self.refs = {ref.id: ref for ref in refs}

    async def get_many(self, ids: Any) -> dict[UUID, FileRef]:  # noqa: ANN401
        return {fid: self.refs[fid] for fid in ids if fid in self.refs}


def _content(*tracks: dict[str, Any]) -> StepContent:
    block = VideoBlock(id="v", url="https://youtu.be/x", captions=list(tracks))
    return StepContent(title="t", blocks=[block])


def test_a_track_needs_a_valid_file_id_and_label() -> None:
    """`file_id` is a UUID; the label is 1 to 60 characters."""
    with pytest.raises(ValidationError):
        CaptionTrack.model_validate(_track("uz", "not-a-uuid"))
    with pytest.raises(ValidationError):
        CaptionTrack.model_validate({**_track("uz", UZ), "label": ""})
    with pytest.raises(ValidationError):
        CaptionTrack.model_validate(_track("de", UZ))


@pytest.mark.parametrize(
    "tracks",
    [
        [_track("uz", UZ), _track("uz", RU)],
        [_track("uz", UZ, default=True), _track("ru", RU, default=True)],
        [_track("uz", UZ), _track("ru", RU), _track("en", UZ), _track("en", RU)],
    ],
)
def test_inconsistent_tracks_are_refused(tracks: list[dict[str, Any]]) -> None:
    """One track per language, at most one default, at most three tracks."""
    with pytest.raises(ValidationError):
        VideoBlock(url="https://youtu.be/x", captions=tracks)


def test_caption_files_are_referenced_and_rendered() -> None:
    """Caption files count as used files; students see lang, label and default."""
    data = _content(_track("uz", UZ, default=True), _track("ru", RU)).model_dump(
        mode="json"
    )

    assert caption_file_ids(data) == [UUID(UZ), UUID(RU)]
    assert set(extract_file_ids(data)) == {UUID(UZ), UUID(RU)}
    block = render_step(_content(_track("uz", UZ)), revision_id="r")["blocks"][0]
    assert block["captions"][0]["lang"] == "uz"


async def test_the_draft_writer_accepts_lms_captions_files() -> None:
    """A finished `lms_captions` upload passes."""
    files = _Files(_ref(UZ, FilePurpose.LMS_CAPTIONS))
    writer = StepDraftWriter(files)  # type: ignore[arg-type]

    prepared = await writer.prepare_new(_content(_track("uz", UZ)))

    assert prepared.file_ids == [UUID(UZ)]


async def test_the_draft_writer_refuses_another_purpose() -> None:
    """A random file of the user cannot be a caption track."""
    files = _Files(_ref(UZ, FilePurpose.LINK))
    writer = StepDraftWriter(files)  # type: ignore[arg-type]

    with pytest.raises(ContentInvalidError) as caught:
        await writer.prepare_new(_content(_track("uz", UZ)))

    assert caught.value.params["reason"] == "caption-file"
