"""
Colour conversions and naming.

Small helpers used by the rest of the program. Everything here works on a single
colour at a time; callers loop. There is no NumPy anywhere in this project --
plain Python is fast enough at these image sizes and is far easier to read.
"""

from __future__ import annotations

import colorsys
from typing import List, Tuple

RGB = Tuple[int, int, int]


def rgb_to_hex(colour: RGB) -> str:
    """(255, 87, 51) -> '#FF5733'."""
    red, green, blue = (max(0, min(255, int(round(c)))) for c in colour)
    return "#{:02X}{:02X}{:02X}".format(red, green, blue)


def hex_to_rgb(value: str) -> RGB:
    """
    '#FF5733' -> (255, 87, 51). Also accepts 'FF5733' and the shorthand '#F53'.

    Raises:
        ValueError: If the text is not a hex colour.
    """
    text = value.strip().lstrip("#")
    if len(text) == 3:
        # '#F53' is shorthand for '#FF5533' -- each digit doubled.
        text = "".join(character * 2 for character in text)
    if len(text) != 6:
        raise ValueError(f"'{value}' is not a valid hex colour.")
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        raise ValueError(f"'{value}' is not a valid hex colour.") from None


def rgb_to_hsv(colour: RGB) -> Tuple[float, float, float]:
    """
    Convert a colour to ``(hue 0-360, saturation 0-1, brightness 0-1)``.

    HSV describes colour the way people do -- *which* colour (hue), *how vivid*
    (saturation) and *how bright* (brightness) -- rather than how a screen makes
    it. That is what lets "ignore washed-out colours" be a single threshold on
    saturation, instead of an endless list of specific grey RGB values.

    ``colorsys`` is part of the Python standard library, so this needs nothing
    installed. It returns hue as 0-1, which is rescaled to degrees here because
    degrees are easier to reason about on a colour wheel.
    """
    hue, saturation, value = colorsys.rgb_to_hsv(
        colour[0] / 255.0, colour[1] / 255.0, colour[2] / 255.0
    )
    return (hue * 360.0, saturation, value)


def hsv_to_rgb(hue: float, saturation: float, value: float) -> RGB:
    """The reverse of :func:`rgb_to_hsv`. Hue is in degrees."""
    red, green, blue = colorsys.hsv_to_rgb((hue % 360.0) / 360.0, saturation, value)
    return (int(round(red * 255)), int(round(green * 255)), int(round(blue * 255)))


def relative_luminance(colour: RGB) -> float:
    """
    How bright a colour looks, from 0.0 (black) to 1.0 (white).

    Green contributes far more to perceived brightness than blue does, which is
    why the three channels are weighted so differently. These are the sRGB
    coefficients from the WCAG contrast standard; the frontend uses the result to
    decide whether a swatch needs black or white text on top of it.
    """
    channels = []
    for raw in colour:
        level = raw / 255.0
        # Undo the gamma curve that sRGB applies, to get true light intensity.
        if level <= 0.04045:
            channels.append(level / 12.92)
        else:
            channels.append(((level + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


# A small vocabulary of colour names. Nearest match against this list turns a
# bare hex code into something a person can read aloud.
#
# The muted entries at the end matter more than they look: with only saturated
# primaries and neutrals in the list, every washed-out colour -- which is most of
# a real photograph -- came out nearest to "Grey".
NAMED_COLOURS: List[Tuple[str, RGB]] = [
    ("Black", (0, 0, 0)),
    ("Charcoal", (54, 54, 58)),
    ("Grey", (128, 128, 128)),
    ("Silver", (192, 192, 192)),
    ("White", (255, 255, 255)),
    ("Cream", (250, 243, 221)),
    ("Beige", (222, 205, 175)),
    ("Brown", (124, 78, 44)),
    ("Tan", (196, 155, 106)),
    ("Maroon", (110, 30, 40)),
    ("Red", (219, 40, 40)),
    ("Coral", (243, 118, 96)),
    ("Orange", (240, 140, 30)),
    ("Gold", (232, 185, 40)),
    ("Yellow", (245, 230, 60)),
    ("Olive", (120, 124, 46)),
    ("Lime", (140, 205, 60)),
    ("Green", (52, 150, 70)),
    ("Forest Green", (28, 88, 52)),
    ("Teal", (36, 148, 148)),
    ("Cyan", (86, 208, 220)),
    ("Sky Blue", (120, 180, 230)),
    ("Blue", (44, 96, 200)),
    ("Navy", (28, 46, 96)),
    ("Indigo", (80, 60, 160)),
    ("Purple", (134, 74, 178)),
    ("Magenta", (208, 70, 178)),
    ("Pink", (240, 150, 185)),
    ("Mauve", (158, 110, 122)),
    ("Plum", (108, 62, 92)),
    ("Rust", (168, 88, 56)),
    ("Slate", (108, 122, 140)),
    ("Sage", (140, 158, 130)),
    ("Dusty Pink", (198, 148, 148)),
]


def describe_colour(colour: RGB) -> str:
    """
    Find the closest human-readable name for a colour.

    Distance is measured with the "redmean" formula rather than plain
    straight-line RGB distance. Straight RGB distance disagrees with human
    vision -- it over-weights blue and under-weights green -- so a plain nearest
    match produces names that feel wrong. Redmean is a well-known correction that
    gets most of the benefit of a full perceptual colour space for a few lines of
    arithmetic.
    """
    red, green, blue = float(colour[0]), float(colour[1]), float(colour[2])

    best_name = "Unknown"
    best_distance = float("inf")

    for name, (other_red, other_green, other_blue) in NAMED_COLOURS:
        # The weightings shift depending on how red the two colours are on
        # average -- that is the correction redmean makes.
        average_red = (red + other_red) / 2.0
        delta_red = red - other_red
        delta_green = green - other_green
        delta_blue = blue - other_blue

        distance = (
            (2 + average_red / 256.0) * delta_red * delta_red
            + 4.0 * delta_green * delta_green
            + (2 + (255.0 - average_red) / 256.0) * delta_blue * delta_blue
        )
        if distance < best_distance:
            best_distance = distance
            best_name = name

    return best_name
