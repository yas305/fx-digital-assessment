"""Small helpers for building test images without any extra dependencies."""

from __future__ import annotations

import io
from typing import Tuple

from PIL import Image, ImageDraw

RGB = Tuple[int, int, int]


def encode(image: Image.Image, fmt: str = "PNG") -> bytes:
    """Turn a Pillow image into raw file bytes."""
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def solid(colour: RGB, width: int = 60, height: int = 40) -> Image.Image:
    """A rectangle of one flat colour."""
    return Image.new("RGB", (width, height), colour)


def bands(*sections) -> Image.Image:
    """
    Vertical bands of known width, e.g. ``bands(((34,148,148), 60), ...)``.

    Widths are in pixels and the image is 100 tall, so a width of 60 out of 100
    is exactly 60% of the pixels -- which makes the expected answer checkable by
    hand rather than a matter of opinion.
    """
    width = sum(w for _colour, w in sections)
    image = Image.new("RGB", (width, 100))
    draw = ImageDraw.Draw(image)
    x = 0
    for colour, section_width in sections:
        draw.rectangle([x, 0, x + section_width - 1, 100], fill=colour)
        x += section_width
    return image
