"""Video blocks: link or uploaded file, validated by `file_id`, and the file check."""

from typing import Any
from uuid import UUID, uuid4

from app.modules.lms.application.authoring.draft_writer import StepDraftWriter
from app.modules.lms.domain.authoring.content_edit import extract_file_ids
from app.modules.lms.domain.authoring.errors import ContentInvalidError
from app.modules.lms.domain.step_content import StepContent, VideoBlock
from app.modules.lms.domain.student_render import render_step
from app.shared.contracts.files import FilePurpose, FileRef, FileScope

import pytest
from pydantic import ValidationError

FILE_ID = str(uuid4())


def _ref(file_id: str, *, purpose: FilePurpose, status: str = "ready") -> FileRef:
    return FileRef(
        id=UUID(file_id),
        owner_id=uuid4(),
        scope=FileScope.STAFF,
        purpose=purpose,
        name="lesson.mp4",
        content_type="video/mp4",
        byte_size=10,
        status=status,
        text_bytes=None,
    )


class _Files:
    """Only `get_many` of the files API."""

    def __init__(self, *refs: FileRef) -> None:
        self.refs = {ref.id: ref for ref in refs}

    async def get_many(self, ids: Any) -> dict[UUID, FileRef]:  # noqa: ANN401
        return {fid: self.refs[fid] for fid in ids if fid in self.refs}


def test_an_uploaded_video_needs_a_valid_file_id() -> None:
    """source=upload without a UUID file_id is invalid."""
    with pytest.raises(ValidationError):
        VideoBlock(source="upload")
    with pytest.raises(ValidationError):
        VideoBlock(source="upload", file_id="not-a-uuid")


def test_an_uploaded_video_drops_the_link_and_a_link_drops_the_file() -> None:
    """The two sources never mix in stored content."""
    upload = VideoBlock(source="upload", file_id=FILE_ID, url="https://x.test/a.mp4")
    link = VideoBlock(source="link", url="https://youtu.be/x", file_id=FILE_ID)

    assert upload.url == "" and upload.file_id == FILE_ID
    assert link.file_id is None and link.url == "https://youtu.be/x"


def test_the_student_render_carries_the_file_id_but_no_url() -> None:
    """The player asks the LMS for a signed URL by block."""
    content = StepContent(
        title="t", blocks=[VideoBlock(id="v", source="upload", file_id=FILE_ID)]
    )

    block = render_step(content, revision_id="r")["blocks"][0]

    assert block["file_id"] == FILE_ID and block["url"] == ""


def test_uploaded_video_files_count_as_referenced_files() -> None:
    """`step.file_ids` lists the video file so the files module can see it is used."""
    data = StepContent(
        title="t",
        blocks=[
            VideoBlock(id="v", source="upload", file_id=FILE_ID),
            VideoBlock(id="w", source="link", url="https://youtu.be/x"),
        ],
    ).model_dump(mode="json")

    assert extract_file_ids(data) == [UUID(FILE_ID)]


async def test_a_ready_lms_video_file_is_accepted() -> None:
    """Draft writer: purpose lms_video and a finished upload pass."""
    files = _Files(_ref(FILE_ID, purpose=FilePurpose.LMS_VIDEO, status="processing"))
    writer = StepDraftWriter(files)  # type: ignore[arg-type]
    content = StepContent(
        title="t", blocks=[VideoBlock(source="upload", file_id=FILE_ID)]
    )

    prepared = await writer.prepare_new(content)

    assert prepared.file_ids == [UUID(FILE_ID)]


@pytest.mark.parametrize(
    "ref",
    [
        _ref(FILE_ID, purpose=FilePurpose.LINK),
        _ref(FILE_ID, purpose=FilePurpose.LMS_VIDEO, status="pending"),
    ],
)
async def test_other_purposes_and_unfinished_uploads_are_refused(
    ref: FileRef,
) -> None:
    """A random file of the user (or a pending upload) cannot be a lesson video."""
    writer = StepDraftWriter(_Files(ref))  # type: ignore[arg-type]
    content = StepContent(
        title="t", blocks=[VideoBlock(source="upload", file_id=FILE_ID)]
    )

    with pytest.raises(ContentInvalidError):
        await writer.prepare_new(content)
