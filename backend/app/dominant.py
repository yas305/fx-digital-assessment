"""
Finding the dominant colour of an image.

The whole algorithm, in the order it happens:

    load  ->  filter  ->  count  ->  rank

Two ways of counting are implemented, and they answer different questions:

  * The histogram rounds every colour onto a fixed grid and counts the cells.
    "Which single shade appears most often?"
  * Median cut draws boxes that fit the image, with no fixed grid at all.
    "If I had to describe this image with a few colours, which few?"

There are no classes in this file, and no NumPy. Colours are plain (red, green,
blue) tuples, images are plain lists of them, and results are plain dictionaries.
Pillow is used only to decode the image file; every calculation after that is
standard Python.
"""

from __future__ import annotations

import io
import random
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, UnidentifiedImageError

from .colour import rgb_to_hsv

# A colour is (red, green, blue), each 0-255. An image is a list of them.
RGB = Tuple[int, int, int]


# ===========================================================================
#  Loading
# ===========================================================================

# Refuse absurdly large images: a small file can otherwise expand to gigabytes.
Image.MAX_IMAGE_PIXELS = 128_000_000

# Pixels more see-through than this are treated as not being there at all.
# This matters: a PNG logo on a transparent background still stores a colour
# under the see-through part, usually black. Counting invisible pixels hands the
# win to a colour nobody can see.
ALPHA_THRESHOLD = 8

# Shrink images so the longest edge is at most this before analysing. A dominant
# colour is a statistical property, so inspecting all 12 million pixels of a
# photograph buys accuracy nobody can perceive.
DEFAULT_MAX_DIMENSION = 400


class ImageLoadError(ValueError):
    """The uploaded bytes could not be read as a usable image."""


def load_image(data: bytes, max_dimension: Optional[int] = DEFAULT_MAX_DIMENSION) -> dict:
    """
    Turn raw image bytes into a list of (red, green, blue) pixels.

    Every messy detail of image formats -- palettes, greyscale, CMYK,
    transparency, huge photographs -- is dealt with here, once, so nothing
    downstream has to think about any of it.

    Returns a dictionary:

        pixels              the visible pixels, ready to count
        grid                every pixel, row by row, including hidden ones
        visible             True/False per grid pixel, or None if none are hidden
        width, height       the size we actually looked at, after shrinking
        original_width      the size before shrinking
        original_height
        format, mode        "JPEG", "RGBA", and so on
        transparent_dropped how many pixels were hidden

    Raises:
        ImageLoadError: if the bytes cannot be decoded or nothing visible remains.
    """
    if not data:
        raise ImageLoadError("The uploaded file is empty.")

    try:
        image = Image.open(io.BytesIO(data))
        # .open() only reads the header, so force the full decode now. A corrupt
        # file then fails here rather than somewhere less convenient later.
        image.load()
    except UnidentifiedImageError as exc:
        raise ImageLoadError(
            "That file could not be read as an image. Supported formats include "
            "JPEG, PNG, GIF, BMP, WEBP and TIFF."
        ) from exc
    except Image.DecompressionBombError as exc:
        raise ImageLoadError("That image is too large to process safely.") from exc
    except OSError as exc:
        raise ImageLoadError(f"That image appears to be corrupt: {exc}") from exc

    original_width, original_height = image.size
    if original_width == 0 or original_height == 0:
        raise ImageLoadError("That image has no pixels.")

    image_format = image.format or "UNKNOWN"
    original_mode = image.mode

    # Animated formats decode to their first frame, which is the sensible
    # reading of "the colour of this image".
    if getattr(image, "is_animated", False):
        image.seek(0)

    if max_dimension is not None and max(image.size) > max_dimension:
        # NEAREST rather than the prettier LANCZOS, deliberately. Smooth
        # resampling blends neighbouring pixels, inventing colours that were
        # never in the image -- exactly the thing we are trying to measure.
        # NEAREST just picks existing pixels, so shrinking samples the real
        # colours rather than distorting them.
        image = image.copy()
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.NEAREST)

    width, height = image.size

    if image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = list(image.convert("RGBA").getdata())
        grid = [(red, green, blue) for red, green, blue, _alpha in rgba]
        visible = [alpha >= ALPHA_THRESHOLD for _r, _g, _b, alpha in rgba]
        pixels = [colour for colour, shown in zip(grid, visible) if shown]
    else:
        # .convert("RGB") normalises greyscale, palette and CMYK in one step.
        grid = list(image.convert("RGB").getdata())
        visible = None
        pixels = grid          # the same list; nothing was hidden

    if not pixels:
        raise ImageLoadError(
            "That image is entirely transparent -- there is nothing to measure."
        )

    return {
        "pixels": pixels,
        "grid": grid,
        "visible": visible,
        "width": width,
        "height": height,
        "original_width": original_width,
        "original_height": original_height,
        "format": image_format,
        "mode": original_mode,
        "transparent_dropped": len(grid) - len(pixels),
    }


# ===========================================================================
#  Filtering -- optionally leaving colours out before counting
# ===========================================================================


def distance_squared(first: RGB, second: RGB) -> int:
    """
    How far apart two colours are, squared.

    Subtract each channel, square the differences (so negatives become
    positive), add them up. A small number means the colours look alike.

    The square root is skipped on purpose. This is only ever used to ask "is
    this closer than that?", and whichever distance is smallest also has the
    smallest square, so taking the root would be wasted work.
    """
    red = first[0] - second[0]
    green = first[1] - second[1]
    blue = first[2] - second[2]
    return red * red + green * green + blue * blue


def apply_filters(
    pixels: List[RGB],
    min_saturation: float = 0.0,
    min_lightness: float = 0.0,
    max_lightness: float = 1.0,
    ignore_colours: Sequence[RGB] = (),
    tolerance: int = 24,
) -> Tuple[List[RGB], Dict[str, int]]:
    """
    Remove unwanted pixels before counting.

    The rules are written in HSV rather than RGB because HSV separates how vivid
    a colour is from which colour it is. That makes "ignore washed-out greys" a
    single threshold rather than a blocklist of specific grey values.

    A product photographed on a white studio background is the motivating case:
    the literal dominant colour is the backdrop, which is never what anyone wants.

    Each excluded pixel is counted against the *first* rule that rejects it, so
    the tallies add up. A white pixel breaks several rules at once; counting it
    under each would overstate how much was removed.

    Returns ``(kept_pixels, counts)`` where counts has the keys
    ``low_saturation``, ``too_dark``, ``too_light``, ``ignored`` and ``total``.
    """
    nothing_to_do = (
        min_saturation <= 0.0
        and min_lightness <= 0.0
        and max_lightness >= 1.0
        and not ignore_colours
    )
    removed = {"low_saturation": 0, "too_dark": 0, "too_light": 0, "ignored": 0, "total": 0}
    if nothing_to_do:
        return pixels, removed

    kept = []
    tolerance_squared = tolerance * tolerance

    for pixel in pixels:
        _hue, saturation, lightness = rgb_to_hsv(pixel)

        if saturation < min_saturation:
            removed["low_saturation"] += 1
        elif lightness < min_lightness:
            removed["too_dark"] += 1
        elif lightness > max_lightness:
            removed["too_light"] += 1
        elif any(
            distance_squared(pixel, unwanted) <= tolerance_squared
            for unwanted in ignore_colours
        ):
            removed["ignored"] += 1
        else:
            kept.append(pixel)

    removed["total"] = len(pixels) - len(kept)
    return kept, removed


# ===========================================================================
#  Method one: the histogram
# ===========================================================================

# Sensible limits on the rounding step. Below about 4 the noise problem returns;
# above about 64 every image collapses to a handful of muddy averages.
MIN_BUCKET_SIZE = 2
MAX_BUCKET_SIZE = 64


def quantise_pixel(pixel: RGB, bucket_size: int) -> RGB:
    """
    Round all three channels down to a multiple of ``bucket_size``.

        quantise_pixel((250, 214, 7), 16) == (240, 208, 0)
        quantise_pixel((251, 215, 8), 16) == (240, 208, 0)

    ``//`` is floor division: divide, then throw the remainder away. So
    ``250 // 16`` is 15, and ``15 * 16`` is 240. Two pixels a person would call
    the same colour now *are* the same value, so their counts add together.

    Rounding down rather than to the nearest multiple is deliberate: rounding to
    nearest makes the first and last buckets half-width, which quietly biases
    results toward pure black and pure white -- the two colours most likely to be
    a background nobody cares about.
    """
    return (
        pixel[0] // bucket_size * bucket_size,
        pixel[1] // bucket_size * bucket_size,
        pixel[2] // bucket_size * bucket_size,
    )


def count_colours(
    pixels: List[RGB], bucket_size: int = 16, top_n: int = 1
) -> Tuple[List[dict], int]:
    """
    Round every colour onto a grid, count the cells, return the fullest.

    Why round at all? There are 256 x 256 x 256 = 16.7 million possible colours.
    A photograph of a blue sky holds thousands of slightly different blues, which
    a person calls one colour and a computer counts as thousands, each with a
    tally of about one. Meanwhile any small patch of flat colour wins by default.

    Returns ``(results, how_many_buckets_the_image_used)``. Each result is a
    dictionary with ``rgb``, ``bucket``, ``count`` and ``share``. That second
    return value is how colourful the image is, and it is what the animation's
    "other" column represents.
    """
    if not pixels:
        return [], 0

    # Two dictionaries do all the work:
    #   how_many[bucket]        one number: how many pixels are in this cell
    #   channel_totals[bucket]  THREE numbers: [red total, green total, blue total]
    #
    # The three totals are kept separately and never added to each other. Red
    # only ever accumulates into red. At the end each is divided by the count on
    # its own, giving the average red, average green and average blue -- which
    # packed back into a tuple is the average colour.
    #
    # They accumulate the ORIGINAL, unrounded values, which is what lets the
    # bucket report a colour genuinely present in the image rather than the grid
    # corner it was filed under.
    #
    # A dictionary is the right tool because looking a bucket up costs the same
    # whether there are ten buckets or ten thousand.
    how_many: Dict[RGB, int] = {}
    channel_totals: Dict[RGB, List[int]] = {}

    for pixel in pixels:
        bucket = quantise_pixel(pixel, bucket_size)

        if bucket not in how_many:
            how_many[bucket] = 0
            channel_totals[bucket] = [0, 0, 0]

        how_many[bucket] += 1

        totals = channel_totals[bucket]
        totals[0] += pixel[0]      # red   into the red total
        totals[1] += pixel[1]      # green into the green total
        totals[2] += pixel[2]      # blue  into the blue total

    # Fullest bucket first. The second half of the sort key only matters for
    # ties, but without it the winner of a tie would depend on the order the
    # pixels happened to appear in, and the same image could give two answers.
    ranked = sorted(how_many, key=lambda bucket: (-how_many[bucket], bucket))

    total = len(pixels)
    results = []

    for bucket in ranked[: max(top_n, 1)]:
        count = how_many[bucket]
        totals = channel_totals[bucket]

        # Report the average of the real pixels, not the bucket's label. The
        # label is a corner of a grid cell and may be a shade found nowhere in
        # the image; the average of its members definitely exists in it.
        results.append(
            {
                # Each channel is averaged on its own: total red / count,
                # total green / count, total blue / count.
                "rgb": (
                    round(totals[0] / count),
                    round(totals[1] / count),
                    round(totals[2] / count),
                ),
                "bucket": bucket,
                "count": count,
                "share": count / total,
            }
        )

    return results, len(how_many)


# ===========================================================================
#  Method two: median cut
# ===========================================================================
#
# The histogram's weakness is that its grid lines are decided before anyone
# looks at the image, so a smoothly shaded object gets sliced across several
# cells that then compete against each other.
#
# Median cut draws the boundaries to fit the image instead:
#
#   1. Put every pixel in one big box.
#   2. Look at that box: which of red, green or blue is most spread out?
#   3. Cut the box in two at the middle VALUE of that channel's range. If the
#      reds in the box run 34 to 240, the cut is at 137: everything at or below
#      goes in one box, everything above in the other.
#   4. Find whichever box is now most spread out, and cut that one.
#   5. Repeat until there are as many boxes as the caller asked for.
#   6. Each box's average colour is one of the answers.
#
# Step 5 is worth being precise about: "as many as asked for" is a number passed
# in, not something worked out here. The loop is `while len(boxes) < box_count`.
# Each cut adds exactly one box, so reaching N boxes takes N-1 cuts.
#
# There is no randomness, nothing repeats until it settles, and the same image
# always gives the same answer. Textbook median cut splits at the middle PIXEL
# rather than the middle value; see split_box for why this does not.
#
# Splitting the *most spread out* box rather than the *biggest* box matters. A
# large area of near-identical colour has almost no spread, so it is left alone
# and stays one box holding a lot of pixels -- which is exactly what a dominant
# colour is. Always splitting the biggest box would chop that region up and
# leave every box roughly the same size.


def widest_channel(box: List[RGB]) -> Tuple[int, int]:
    """
    Find which channel varies most inside a box.

    Returns ``(channel, spread)`` where channel is 0, 1 or 2 for red, green or
    blue, and spread is the gap between the highest and lowest value found.
    A spread of 0 means every pixel in the box is identical on every channel.
    """
    best_channel = 0
    best_spread = -1

    for channel in range(3):
        lowest = min(pixel[channel] for pixel in box)
        highest = max(pixel[channel] for pixel in box)
        spread = highest - lowest
        if spread > best_spread:
            best_spread = spread
            best_channel = channel

    return best_channel, best_spread


def average_colour(box: List[RGB]) -> RGB:
    """
    The average of every pixel in a box, one channel at a time.

    Identical to how the histogram averages a bucket: add up all the reds and
    divide by the count, then the same for green and blue.
    """
    count = len(box)
    return (
        round(sum(pixel[0] for pixel in box) / count),
        round(sum(pixel[1] for pixel in box) / count),
        round(sum(pixel[2] for pixel in box) / count),
    )


def split_box(box: List[RGB], at_median: bool = False) -> Tuple[List[RGB], List[RGB]]:
    """
    Cut one box into two, along whichever channel is most spread out.

    There are two sensible places to cut, and the choice matters a lot:

    **Midpoint** (the default here) cuts at the middle *value* of the range.
    If a box holds reds from 34 to 240, it cuts at 137.

    **Median** cuts at the middle *pixel* -- sort the box and split it in half,
    so both halves hold the same number of pixels. This is what the textbook
    median cut algorithm does.

    Median is the right choice when you want a balanced palette, which is what
    the algorithm was designed for: every colour in the palette then represents
    a similar share of the image.

    It is the wrong choice here. We want the *dominant* colour, and cutting at
    the median deliberately chops large uniform regions in half. On the blocks
    demo -- 60% teal, 30% orange, 10% blue -- the median falls inside the run of
    teal, so the teal block is split in two and the answer comes out as 50%
    rather than 60%. Cutting at the midpoint of the range leaves the teal alone.
    """
    channel, _spread = widest_channel(box)

    if at_median:
        ordered = sorted(box, key=lambda pixel: pixel[channel])
        middle = len(ordered) // 2
        return ordered[:middle], ordered[middle:]

    lowest = min(pixel[channel] for pixel in box)
    highest = max(pixel[channel] for pixel in box)
    threshold = (lowest + highest) / 2

    left = [pixel for pixel in box if pixel[channel] <= threshold]
    right = [pixel for pixel in box if pixel[channel] > threshold]

    # With a real spread this cannot produce an empty side -- the lowest pixel is
    # always at or below the midpoint and the highest is always above it. The
    # guard is here for the degenerate case where every pixel in the box shares
    # the same value on this channel, which median_cut already avoids by never
    # cutting a box with zero spread.
    if not left or not right:
        ordered = sorted(box, key=lambda pixel: pixel[channel])
        middle = len(ordered) // 2
        return ordered[:middle], ordered[middle:]

    return left, right


def median_cut(
    pixels: List[RGB],
    box_count: int = 5,
    record_steps: bool = False,
    at_median: bool = False,
) -> dict:
    """
    Split the image's colours into ``box_count`` boxes, biggest first.

    Args:
        pixels: The image as (red, green, blue) triples.
        box_count: How many boxes to end up with.
        record_steps: Also return the state after every split, for the
            animation. The algorithm itself does not need this.
        at_median: Cut at the middle pixel rather than the middle value. See
            :func:`split_box` -- textbook behaviour, but worse for finding a
            dominant colour.

    Returns a dictionary:

        results   the boxes, biggest first, same shape as count_colours
        splits    how many cuts were made
        steps     one entry per cut, if record_steps was set. Each holds the
                  box colours and a colour -> box number lookup.
    """
    if not pixels:
        return {"results": [], "splits": 0, "steps": []}

    boxes: List[List[RGB]] = [list(pixels)]
    steps: List[dict] = [_describe(boxes)] if record_steps else []
    splits = 0

    while len(boxes) < box_count:
        # Which box is worth cutting? The one whose colours are most spread
        # out. Boxes holding a single pixel, or pixels that are all identical,
        # cannot be cut at all.
        best_index = -1
        best_spread = 0
        for index, box in enumerate(boxes):
            if len(box) < 2:
                continue
            _channel, spread = widest_channel(box)
            if spread > best_spread:
                best_spread = spread
                best_index = index

        if best_index == -1:
            # Every box is either a single pixel or entirely one colour. There
            # is nothing left to cut, so we stop early with fewer boxes than
            # asked for -- the image simply does not contain that many colours.
            break

        left, right = split_box(boxes[best_index], at_median=at_median)
        boxes[best_index : best_index + 1] = [left, right]
        splits += 1

        if record_steps:
            steps.append(_describe(boxes))

    total = len(pixels)
    results = [
        {
            "rgb": average_colour(box),
            "bucket": average_colour(box),
            "count": len(box),
            "share": len(box) / total,
        }
        for box in boxes
        if box
    ]
    # Biggest first, ties broken by colour so the order is reproducible.
    results.sort(key=lambda result: (-result["count"], result["rgb"]))

    return {"results": results, "splits": splits, "steps": steps}


def _describe(boxes: List[List[RGB]]) -> dict:
    """
    Snapshot the boxes for the animation.

    Records each box's average colour, and a lookup saying which box every
    colour ended up in, so the animation can colour each dot correctly.
    Used only when ``record_steps`` is on -- the algorithm itself never needs it.
    """
    lookup: Dict[RGB, int] = {}
    for index, box in enumerate(boxes):
        for colour in box:
            lookup[colour] = index

    return {
        "colours": [average_colour(box) for box in boxes if box],
        "lookup": lookup,
    }


# ===========================================================================
#  Sampling, for the algorithm animation
# ===========================================================================

# Enough pixels to read as a crowd and show real structure, few enough to
# animate smoothly and send over the wire without thinking about it.
DEFAULT_SAMPLE_SIZE = 420

# Fixed so the same image always animates identically. A visualisation that
# reshuffles itself every run is distracting to demonstrate.
SAMPLE_SEED = 1234


def sample_pixels(image: dict, how_many: int = DEFAULT_SAMPLE_SIZE) -> List[tuple]:
    """
    Pick a representative set of pixels, keeping track of where each one sits.

    Returns a list of ``(colour, x, y)`` with x and y from 0 to 1, so the
    frontend can lay the sample out in the image's own shape whatever its aspect
    ratio. Animating a million pixels is neither possible nor useful; a few
    hundred shows the shape of what happens.
    """
    grid, visible = image["grid"], image["visible"]
    indexes = [i for i in range(len(grid)) if visible is None or visible[i]]
    if not indexes:
        return []

    if len(indexes) > how_many:
        indexes = sorted(random.Random(SAMPLE_SEED).sample(indexes, how_many))

    width = image["width"]
    widest = max(width - 1, 1)
    tallest = max(image["height"] - 1, 1)

    return [
        (grid[i], (i % width) / widest, (i // width) / tallest) for i in indexes
    ]
