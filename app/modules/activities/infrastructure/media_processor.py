"""Club media processing: sniff the real type, strip metadata, build derivatives.

Photos go through Pillow (EXIF incl. GPS dropped, orientation applied, WebP out);
videos through ffprobe/ffmpeg child processes with hard bounds (no shell, no network
protocols, wall-clock timeout, two threads, one processing run at a time; video
frame sizes are bounded by ffprobe before anything decodes them). Nothing here trusts
the declared type or the file name: the content decides.
"""

import asyncio
import importlib
import io
import json
import shutil
import tempfile
from pathlib import Path
from typing import Final

from app.modules.activities.domain.media import (
    MediaKind,
    MediaTooLargeError,
    MediaTypeNotAllowedError,
    MediaVariant,
)
from app.modules.activities.ports.gateways import Derivative, MediaProbe

import magic
from PIL import Image, ImageOps, UnidentifiedImageError

__all__ = ["Derivative", "MediaProbe", "PillowFfmpegMediaProcessor"]

MAX_PIXELS: Final = 50_000_000
MAX_VIDEO_PIXELS: Final = 4096 * 4096
THUMB_SIDE: Final = 320
PREVIEW_SIDE: Final = 1600
POSTER_SIDE: Final = 1280
MAX_VIDEO_SECONDS: Final = 600
FFMPEG_TIMEOUT_SECONDS: Final = 600.0
PROBE_TIMEOUT_SECONDS: Final = 30.0
_SNIFF_BYTES: Final = 4096

_PHOTO_TYPES: Final = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/tiff",
        "image/heic",
        "image/heif",
    }
)
_VIDEO_TYPES: Final = frozenset(
    {
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "video/x-matroska",
        "video/x-msvideo",
        "video/3gpp",
    }
)
# 8 GB hosts: one probe/decode/transcode run at a time, photos and videos alike.
_PROCESS_SLOT = asyncio.Semaphore(1)
Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # Pillow raises DecompressionBombError at 2x


def _register_heif() -> bool:
    try:
        heif = importlib.import_module("pillow_heif")
    except ImportError:
        return False
    heif.register_heif_opener()
    return True


HEIF_SUPPORTED: Final = _register_heif()


def sniff_content_type(path: Path) -> str:
    """Return the real MIME type of the file, whatever its name says."""
    with path.open("rb") as handle:
        head = handle.read(_SNIFF_BYTES)
    return str(magic.from_buffer(head, mime=True))


def _allowed_photo(content_type: str) -> bool:
    if content_type in {"image/heic", "image/heif"}:
        return HEIF_SUPPORTED
    return content_type in _PHOTO_TYPES


class PillowFfmpegMediaProcessor:
    """Implements the activities `MediaProcessor` port with Pillow and ffmpeg."""

    def __init__(
        self,
        *,
        max_video_seconds: int = MAX_VIDEO_SECONDS,
        transcode_enabled: bool = True,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
    ) -> None:
        """Keep the caps and the binaries to run."""
        self._max_seconds = max_video_seconds
        self._transcode = transcode_enabled
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe

    async def probe(self, path: Path) -> MediaProbe:
        """Sniff the type and read dimensions/duration.

        Raises:
            MediaTypeNotAllowedError: not a supported photo or video.
            MediaTooLargeError: too many pixels or too long.
        """
        async with _PROCESS_SLOT:
            return await self._probe(path)

    async def _probe(self, path: Path) -> MediaProbe:
        content_type = await asyncio.to_thread(sniff_content_type, path)
        if _allowed_photo(content_type):
            width, height = await asyncio.to_thread(_probe_photo, path)
            return MediaProbe(MediaKind.PHOTO, content_type, width, height, None)
        if content_type in _VIDEO_TYPES:
            return await self._probe_video(path, content_type)
        raise MediaTypeNotAllowedError

    async def make_derivatives(
        self, path: Path, probe: MediaProbe, out_dir: Path
    ) -> list[Derivative]:
        """Write the derivatives of `path` into `out_dir` and return them."""
        async with _PROCESS_SLOT:
            if probe.kind == MediaKind.PHOTO:
                return await asyncio.to_thread(_photo_derivatives, path, out_dir)
            return await self._video_derivatives(path, probe, out_dir)

    async def _probe_video(self, path: Path, content_type: str) -> MediaProbe:
        argv = [
            self._ffprobe,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        code, out = await _run(argv, PROBE_TIMEOUT_SECONDS)
        if code != 0:
            raise MediaTypeNotAllowedError
        try:
            data = json.loads(out)
            stream = next(s for s in data["streams"] if s.get("codec_type") == "video")
            width, height = int(stream["width"]), int(stream["height"])
            seconds = float(data["format"].get("duration") or stream["duration"])
        except (KeyError, StopIteration, ValueError, TypeError):
            raise MediaTypeNotAllowedError from None
        if width <= 0 or height <= 0:
            raise MediaTypeNotAllowedError
        if width * height > MAX_VIDEO_PIXELS:
            raise MediaTooLargeError
        if _rotated(stream):
            width, height = height, width
        if seconds > self._max_seconds:
            raise MediaTooLargeError
        return MediaProbe(
            MediaKind.VIDEO, content_type, width, height, int(seconds * 1000)
        )

    async def _video_derivatives(
        self, path: Path, probe: MediaProbe, out_dir: Path
    ) -> list[Derivative]:
        out_dir.mkdir(parents=True, exist_ok=True)
        seconds = (probe.duration_ms or 0) / 1000
        frame = out_dir / "frame.jpg"
        at = f"{min(1.0, seconds / 2):.3f}"
        # ffmpeg downsizes the frame itself so Pillow never sees full resolution.
        bound = f"scale='min({PREVIEW_SIDE},iw)':'min({PREVIEW_SIDE},ih)'"
        code, _ = await _run(
            self._base(path, "-ss", at)
            + ["-frames:v", "1", "-vf", bound + ":force_original_aspect_ratio=decrease"]
            + ["-q:v", "3", "-an", "-sn", "-y", str(frame)],
            FFMPEG_TIMEOUT_SECONDS,
        )
        if code != 0 or not frame.exists():
            raise MediaTypeNotAllowedError
        result = await asyncio.to_thread(_poster_derivatives, frame, out_dir)
        frame.unlink(missing_ok=True)
        if self._transcode:
            result.append(await self._preview_video(path, out_dir))
        return result

    async def _preview_video(self, path: Path, out_dir: Path) -> Derivative:
        target = out_dir / "preview.mp4"
        scale = "scale=-2:'min(720,ih)'"
        argv = self._base(path) + [
            "-vf",
            scale,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            "-sn",
            "-y",
            str(target),
        ]
        code, _ = await _run(argv, FFMPEG_TIMEOUT_SECONDS)
        if code != 0 or not target.exists():
            raise MediaTypeNotAllowedError
        return Derivative(MediaVariant.VIDEO, target, "video/mp4")

    def _base(self, path: Path, *pre: str) -> list[str]:
        return [
            self._ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "file",
            "-threads",
            "2",
            *pre,
            "-i",
            str(path),
        ]


def _rotated(stream: dict[str, object]) -> bool:
    tags = stream.get("tags")
    rotate = tags.get("rotate") if isinstance(tags, dict) else None
    sides = stream.get("side_data_list")
    if rotate is None and isinstance(sides, list):
        for side in sides:
            if isinstance(side, dict) and "rotation" in side:
                rotate = side["rotation"]
    try:
        return abs(int(float(str(rotate)))) % 180 == 90
    except ValueError:
        return False


def _open_checked(path: Path) -> Image.Image:
    try:
        image = Image.open(path)
        if image.width * image.height > MAX_PIXELS:
            raise MediaTooLargeError
        return image
    except Image.DecompressionBombError:
        raise MediaTooLargeError from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise MediaTypeNotAllowedError from None


def _probe_photo(path: Path) -> tuple[int, int]:
    with _open_checked(path) as image:
        image.load()
        oriented = ImageOps.exif_transpose(image)
        return oriented.width, oriented.height


def _clean(image: Image.Image) -> Image.Image:
    """Apply orientation and return a fresh image with no metadata at all."""
    oriented = ImageOps.exif_transpose(image)
    if oriented.mode not in {"RGB", "RGBA"}:
        oriented = oriented.convert("RGBA" if "A" in oriented.getbands() else "RGB")
    fresh = Image.new(oriented.mode, oriented.size)
    fresh.paste(oriented)
    return fresh


def _webp(
    image: Image.Image, side: int, target: Path, variant: MediaVariant
) -> Derivative:
    copy = image.copy()
    copy.thumbnail((side, side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, "WEBP", quality=80, method=4)  # no exif/icc passed: none written
    target.write_bytes(buffer.getvalue())
    return Derivative(variant, target, "image/webp", copy.width, copy.height)


def _photo_derivatives(path: Path, out_dir: Path) -> list[Derivative]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with _open_checked(path) as image:
        image.load()
        clean = _clean(image)
    return [
        _webp(clean, THUMB_SIDE, out_dir / "thumb.webp", MediaVariant.THUMB),
        _webp(clean, PREVIEW_SIDE, out_dir / "preview.webp", MediaVariant.PREVIEW),
    ]


def _poster_derivatives(frame: Path, out_dir: Path) -> list[Derivative]:
    with _open_checked(frame) as image:
        image.load()
        clean = _clean(image)
    return [
        _webp(clean, THUMB_SIDE, out_dir / "thumb.webp", MediaVariant.THUMB),
        _webp(clean, POSTER_SIDE, out_dir / "poster.webp", MediaVariant.POSTER),
    ]


async def _run(argv: list[str], timeout: float) -> tuple[int, bytes]:
    """Run a child without a shell; kill it on timeout (code 124)."""
    if shutil.which(argv[0]) is None:
        return 127, b""
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return 124, b""
    return int(process.returncode or 0), out


def make_work_dir() -> Path:
    """Return a fresh temp directory for one processing run (caller removes it)."""
    return Path(tempfile.mkdtemp(prefix="club-media-"))
