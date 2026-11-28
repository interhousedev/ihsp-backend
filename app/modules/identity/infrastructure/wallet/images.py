"""PNG images of wallet passes, drawn or resized with Pillow."""

import io

from PIL import Image, ImageDraw, ImageOps

NAVY = (15, 30, 61, 255)
WHITE = (255, 255, 255, 255)


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def emblem_png(size: int) -> bytes:
    """A white rounded square with a navy graduation cap: the default logo."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=WHITE)
    s = size / 24
    board = [(2 * s, 9 * s), (12 * s, 4 * s), (22 * s, 9 * s), (12 * s, 14 * s)]
    draw.polygon(board, fill=NAVY)
    draw.polygon(
        [(6 * s, 11 * s), (18 * s, 11 * s), (18 * s, 17 * s)]
        + [(12 * s, 19 * s), (6 * s, 17 * s)],
        fill=NAVY,
    )
    draw.line([(20 * s, 10 * s), (20 * s, 16 * s)], fill=NAVY, width=max(1, int(s)))
    return _png(image)


def fit_png(data: bytes, width: int, height: int) -> bytes:
    """The image scaled to fit the box, keeping its proportions."""
    with Image.open(io.BytesIO(data)) as source:
        image = source.convert("RGBA")
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    return _png(image)


def square_photo_png(data: bytes, size: int) -> bytes:
    """The photo cropped to a square from its centre."""
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    return _png(ImageOps.fit(image, (size, size), Image.Resampling.LANCZOS))
