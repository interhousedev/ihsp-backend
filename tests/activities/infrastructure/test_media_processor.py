"""Club media processor: metadata stripping, orientation, bombs, spoofing, video."""

import shutil
import subprocess
from pathlib import Path

from app.modules.activities.domain.media import (
    MediaKind,
    MediaTooLargeError,
    MediaTypeNotAllowedError,
    MediaVariant,
)
from app.modules.activities.infrastructure.media_processor import (
    PillowFfmpegMediaProcessor,
)

import pytest
from PIL import Image

processor = PillowFfmpegMediaProcessor()


def _jpeg_with_gps(path: Path, orientation: int = 6) -> None:
    exif = Image.Exif()
    exif[0x0112] = orientation
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (41.0, 18.0, 0.0)
    gps[3] = "E"
    gps[4] = (69.0, 16.0, 0.0)
    Image.new("RGB", (400, 200), (200, 30, 30)).save(path, "JPEG", exif=exif)


async def test_gps_removed_and_orientation_applied(tmp_path: Path) -> None:
    source = tmp_path / "a.jpg"
    _jpeg_with_gps(source)
    assert Image.open(source).getexif().get_ifd(0x8825)
    probe = await processor.probe(source)
    assert probe.kind == MediaKind.PHOTO
    assert (probe.width, probe.height) == (200, 400)  # rotated by EXIF 6
    out = await processor.make_derivatives(source, probe, tmp_path / "out")
    by = {d.variant: d for d in out}
    assert set(by) == {MediaVariant.THUMB, MediaVariant.PREVIEW}
    for derivative in out:
        raw = derivative.path.read_bytes()
        assert b"EXIF" not in raw and b"GPS" not in raw
        image = Image.open(derivative.path)
        assert not image.getexif()
        assert image.height > image.width


async def test_decompression_bomb_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bomb.png"
    Image.new("1", (8000, 8000)).save(source, "PNG")  # 64 MP, tiny file
    with pytest.raises(MediaTooLargeError):
        await processor.probe(source)


async def test_spoofed_extension_rejected(tmp_path: Path) -> None:
    source = tmp_path / "evil.jpg"
    source.write_bytes(b"#!/bin/sh\necho pwned\n" * 20)
    with pytest.raises(MediaTypeNotAllowedError):
        await processor.probe(source)


async def test_corrupt_image_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    with pytest.raises(MediaTypeNotAllowedError):
        await processor.probe(source)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg is not installed",
)
async def test_video_poster_preview_and_duration(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=320x240:rate=10",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source),
        ],
        check=True,
    )
    probe = await processor.probe(source)
    assert probe.kind == MediaKind.VIDEO
    assert (probe.width, probe.height) == (320, 240)
    assert probe.duration_ms is not None and 900 <= probe.duration_ms <= 1200
    out = await processor.make_derivatives(source, probe, tmp_path / "out")
    by = {d.variant: d for d in out}
    assert set(by) == {
        MediaVariant.THUMB,
        MediaVariant.POSTER,
        MediaVariant.VIDEO,
    }
    assert Image.open(by[MediaVariant.POSTER].path).size == (320, 240)
    assert by[MediaVariant.VIDEO].path.stat().st_size > 0


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg is not installed",
)
async def test_video_with_huge_frame_rejected_before_decode(tmp_path: Path) -> None:
    source = tmp_path / "huge.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=4200x4200:d=0.04:r=25",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source),
        ],
        check=True,
    )
    with pytest.raises(MediaTooLargeError):
        await processor.probe(source)
