"""
Demo images, drawn in code rather than shipped as files.

Generating them keeps the repository text-only, but the real reason is that
several have a *known correct answer*. Being able to say "this image is exactly
60% this teal, and the analyser returns exactly that teal" is far stronger
evidence than looking at a photograph and deciding the result seems about right.
"""

from __future__ import annotations

import io
import random
from typing import Dict, List

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 400, 300


def draw_known_proportions() -> Image.Image:
    """Three vertical bands covering exactly 60% / 30% / 10%."""
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, int(WIDTH * 0.6) - 1, HEIGHT], fill=(34, 148, 148))
    draw.rectangle([int(WIDTH * 0.6), 0, int(WIDTH * 0.9) - 1, HEIGHT], fill=(240, 140, 30))
    draw.rectangle([int(WIDTH * 0.9), 0, WIDTH, HEIGHT], fill=(44, 96, 200))
    return image


def draw_noisy_sky() -> Image.Image:
    """A blue sky with per-pixel noise, plus a small patch of perfectly flat white."""
    rng = random.Random(7)
    pixels = [
        (
            120 + rng.randint(-9, 9),
            180 + rng.randint(-9, 9),
            230 + rng.randint(-9, 9),
        )
        for _ in range(WIDTH * HEIGHT)
    ]
    image = Image.new("RGB", (WIDTH, HEIGHT))
    image.putdata(pixels)
    # A flat, perfectly uniform white block over about 7% of the image.
    ImageDraw.Draw(image).rectangle([20, 20, 179, 69], fill=(255, 255, 255))
    return image


def draw_product_on_white() -> Image.Image:
    """A crimson shape on a large white background."""
    image = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    # A soft shadow first, so the image is not trivially two-toned.
    draw.ellipse([110, 215, 290, 265], fill=(232, 228, 230))
    draw.ellipse([122, 72, 278, 228], fill=(200, 40, 60))
    return image


def draw_sunset_gradient() -> Image.Image:
    """A smooth vertical gradient, with almost no repeated colours."""
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    top, bottom = (250, 180, 70), (90, 40, 120)

    for y in range(HEIGHT):
        position = y / (HEIGHT - 1)
        draw.line(
            [(0, y), (WIDTH, y)],
            fill=tuple(
                round(top[c] * (1 - position) + bottom[c] * position) for c in range(3)
            ),
        )
    return image


def draw_greyscale_study() -> Image.Image:
    """Nearly colourless, with one small accent."""
    rng = random.Random(3)
    pixels = []
    for _ in range(HEIGHT):
        for x in range(WIDTH):
            level = max(0, min(255, 40 + (175 * x // (WIDTH - 1)) + rng.randint(-5, 5)))
            pixels.append((level, level, level))

    image = Image.new("RGB", (WIDTH, HEIGHT))
    image.putdata(pixels)
    ImageDraw.Draw(image).rectangle([300, 130, 359, 169], fill=(208, 70, 100))
    return image


def draw_transparent_logo() -> Image.Image:
    """A PNG whose see-through area hides pure black underneath."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(image).polygon(
        [(200, 60), (290, 150), (200, 240), (110, 150)], fill=(134, 74, 178, 255)
    )
    return image


# Each sample is a plain dictionary. "expected" is the known answer where there
# is one, and the tests assert it -- which is what makes these worth having.
SAMPLES: List[dict] = [
    {
        "id": "blocks",
        "name": "Known Proportions",
        "description": "Three bands at exactly 60% / 30% / 10%. The dominant colour is verifiable by hand.",
        "draw": draw_known_proportions,
        "expected": (34, 148, 148),
    },
    {
        "id": "noisy-sky",
        "name": "Noisy Sky",
        "description": "Thousands of near-identical blues plus a small flat white patch. Shows why grouping matters.",
        "draw": draw_noisy_sky,
        "expected": None,
    },
    {
        "id": "product-on-white",
        "name": "Product on White",
        "description": "A crimson shape on a white backdrop. Turn on the white filter to find the product.",
        "draw": draw_product_on_white,
        "expected": (255, 255, 255),
    },
    {
        "id": "sunset",
        "name": "Sunset Gradient",
        "description": "A smooth gradient with almost no repeated colours. Try changing the bucket size.",
        "draw": draw_sunset_gradient,
        "expected": None,
    },
    {
        "id": "greyscale",
        "name": "Greyscale Study",
        "description": "Nearly colourless, with one small accent. Tests how the hue chart handles grey.",
        "draw": draw_greyscale_study,
        "expected": None,
    },
    {
        "id": "transparent",
        "name": "Transparent Logo",
        "description": "A PNG whose transparent area hides black pixels. They must not be counted.",
        "draw": draw_transparent_logo,
        "expected": (134, 74, 178),
    },
]

SAMPLES_BY_ID: Dict[str, dict] = {sample["id"]: sample for sample in SAMPLES}

# These are deterministic and small, so caching them avoids redrawing on every
# request with no invalidation to worry about.
_CACHE: Dict[str, bytes] = {}


def render_sample(sample_id: str) -> bytes:
    """Return a sample image encoded as PNG bytes."""
    if sample_id not in _CACHE:
        buffer = io.BytesIO()
        SAMPLES_BY_ID[sample_id]["draw"]().save(buffer, format="PNG")
        _CACHE[sample_id] = buffer.getvalue()
    return _CACHE[sample_id]
