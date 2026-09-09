"""
Finding the dominant colour of an image.

The whole algorithm, in the order it happens:

    load  ->  filter  ->  count  ->  rank

Two ways of counting are implemented, and they answer different questions:

  * The histogram rounds every colour onto a fixed grid and counts the cells.
    "Which single shade appears most often?"
  * k-means lets groups form where the colours actually cluster, with no grid.
    "If I had to describe this image with k colours, which k?"

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

    16.7 million possible colours.
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
    how_many: Dict[RGB, int] = {}
    channel_totals: Dict[RGB, List[int]] = {}

    for pixel in pixels:
        bucket = quantise_pixel(pixel, bucket_size)

        if bucket not in how_many:
            how_many[bucket] = 0
            channel_totals[bucket] = [0, 0, 0]

        how_many[bucket] += 1

        totals = channel_totals[bucket]
        totals[0] += pixel[0]      
        totals[1] += pixel[1]      
        totals[2] += pixel[2]      

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
#  Method two: k-means clustering
# ===========================================================================
#
# Picture ice-cream vans parking in a town:
#
#   1. Park k vans somewhere sensible.
#   2. Every resident walks to their nearest van.
#   3. Each van moves to the middle of its own customers.
#   4. Some residents now find a different van is nearer, so go back to step 2.
#
# Repeat until the vans stop moving. The town is colour space, the residents are
# pixels standing at their own colour, the vans are the cluster centres, and the
# busiest van is the dominant colour.
#
# The difference from the histogram is where the boundaries fall. The histogram
# draws them on a fixed grid decided before anyone looked at the image, so a
# smoothly shaded object gets sliced into pieces that compete against each other.
# k-means puts its boundaries wherever colours are sparse, so a shaded object
# stays in one group.

DEFAULT_SEED = 42
MAX_ITERATIONS = 40

# Stop once no centre moves further than this in a round. Half a unit of colour
# is far below what an eye can see.
SETTLED = 0.5

# Colours are rounded to multiples of this before clustering.
#
# The one concession to speed in the project, and it is needed: a 400px photo
# holds around 115,000 distinct colours, and clustering that many points in plain
# Python takes minutes. Rounding to multiples of 8 -- a step invisible to the eye
# -- cuts it to about 6,600 and brings the whole thing down to roughly 175ms.
CLUSTER_PRECISION = 8


def distance_squared(first: RGB, second: RGB) -> int:
    """
    How far apart two colours are, squared.

    The square root is skipped on purpose. This is only used to ask "which is
    nearer?", and whichever distance is smallest also has the smallest square, so
    taking the root would be wasted work that changes no answer.
    """
    red = first[0] - second[0]
    green = first[1] - second[1]
    blue = first[2] - second[2]
    return red * red + green * green + blue * blue


def nearest_centre(colour: RGB, centres: Sequence[RGB]) -> int:
    """Return the position of whichever centre is closest to this colour."""
    best_index = 0
    best_distance = distance_squared(colour, centres[0])

    for index in range(1, len(centres)):
        distance = distance_squared(colour, centres[index])
        if distance < best_distance:
            best_index = index
            best_distance = distance

    return best_index


def group_similar_colours(
    pixels: List[RGB], precision: int = CLUSTER_PRECISION
) -> Tuple[List[RGB], List[int]]:
    """
    Collapse near-identical colours together, keeping a count of each.

    Clustering 6,000 weighted colours instead of 160,000 individual pixels is the
    same calculation: the average of a group does not change when you say "this
    colour, 500 times" rather than listing it 500 times.

    Note what each group is *represented* by. Pixels are grouped by their rounded
    colour, but each group reports the average of the **real** colours in it, not
    the rounded value. Otherwise every answer would snap to a multiple of 8, and
    an image of exactly (34, 148, 148) would come back as (32, 144, 144).

    Returns ``(colours, weights)`` -- two lists of the same length.
    """
    counts: Dict[RGB, int] = {}
    channel_totals: Dict[RGB, List[int]] = {}

    for pixel in pixels:
        key = quantise_pixel(pixel, precision)

        if key not in counts:
            counts[key] = 0
            channel_totals[key] = [0, 0, 0]

        counts[key] += 1

        # Three separate totals again -- red into red, green into green, blue
        # into blue. They are never added to one another.
        totals = channel_totals[key]
        totals[0] += pixel[0]
        totals[1] += pixel[1]
        totals[2] += pixel[2]

    colours, weights = [], []
    # Sorted so the order does not depend on which pixel came first, which keeps
    # the whole run reproducible.
    for key in sorted(counts):
        count = counts[key]
        totals = channel_totals[key]
        colours.append(
            (round(totals[0] / count), round(totals[1] / count), round(totals[2] / count))
        )
        weights.append(count)

    return colours, weights


def pick_starting_centres(
    colours: List[RGB], weights: List[int], k: int, rng: random.Random
) -> List[RGB]:
    """
    Choose k starting positions, spread out from one another. ("k-means++")

    Dropping the centres at random risks two landing in the same neighbourhood,
    squabbling over one group while another part of the image is ignored
    entirely. So: pick the first at random, favouring colours many pixels share,
    then pick each of the rest with a strong preference for colours far away from
    every centre already placed.
    """
    first = rng.choices(range(len(colours)), weights=weights, k=1)[0]
    centres = [colours[first]]

    while len(centres) < k:
        # For each colour: how far is it from the nearest centre placed so far?
        # Multiplied by its pixel count, so a distant colour used by one pixel
        # does not outrank a fairly distant one used by thousands.
        scores = [
            min(distance_squared(colour, centre) for centre in centres) * weight
            for colour, weight in zip(colours, weights)
        ]

        if sum(scores) <= 0:
            # Everything left already sits on a centre, so there is nothing
            # meaningfully far away to choose. Any colour will do.
            centres.append(colours[rng.randrange(len(colours))])
        else:
            centres.append(colours[rng.choices(range(len(colours)), weights=scores, k=1)[0]])

    return centres


def cluster_colours(pixels: List[RGB], k: int = 5, seed: int = DEFAULT_SEED) -> dict:
    """
    Group an image's pixels into k colour clusters, biggest first.

    ``seed`` fixes the random starting positions so the same image always gives
    the same answer. Without it, running twice would give two answers -- no use
    in an API.

    Returns a dictionary:

        results     the clusters, biggest first, same shape as count_colours
        iterations  how many rounds it took to settle
        history     the centres after every round, starting with the seeds
        colours     the distinct colours that were clustered
        weights     how many pixels each of those represents

    ``history`` is not needed by the algorithm. The animation replays it, so the
    walkthrough shows the real run rather than a re-enactment of one.
    """
    if not pixels:
        return {"results": [], "iterations": 0, "history": [], "colours": [], "weights": []}

    colours, weights = group_similar_colours(pixels)

    # Asking for more groups than there are colours would leave some empty.
    k = min(max(k, 1), len(colours))

    rng = random.Random(seed)
    centres = pick_starting_centres(colours, weights, k, rng)
    history = [list(centres)]

    iterations = 0
    for iterations in range(1, MAX_ITERATIONS + 1):
        # --- every colour joins its nearest centre -------------------------
        members: List[List[int]] = [[] for _ in centres]
        for index, colour in enumerate(colours):
            members[nearest_centre(colour, centres)].append(index)

        # --- every centre moves to the middle of its members ---------------
        moved = []
        furthest_move = 0.0

        for centre_index, member_indexes in enumerate(members):
            if not member_indexes:
                # Nobody chose this centre. Leave it be; it usually picks up
                # members on a later round.
                moved.append(centres[centre_index])
                continue

            total_weight = sum(weights[i] for i in member_indexes)
            average = tuple(
                round(
                    sum(colours[i][channel] * weights[i] for i in member_indexes)
                    / total_weight
                )
                for channel in range(3)
            )

            furthest_move = max(
                furthest_move, distance_squared(centres[centre_index], average) ** 0.5
            )
            moved.append(average)

        centres = moved
        history.append(list(centres))

        # --- stop once nothing is really moving any more -------------------
        if furthest_move < SETTLED:
            break

    # Count the members one final time, against the settled centres, so the
    # numbers reported match the colours reported.
    totals = [0] * len(centres)
    for colour, weight in zip(colours, weights):
        totals[nearest_centre(colour, centres)] += weight

    results = [
        {
            "rgb": centres[index],
            "bucket": centres[index],
            "count": totals[index],
            "share": totals[index] / len(pixels),
        }
        for index in range(len(centres))
        if totals[index] > 0          # an empty cluster is not a colour
    ]
    # Biggest first, ties broken by colour so the order is reproducible.
    results.sort(key=lambda result: (-result["count"], result["rgb"]))

    return {
        "results": results,
        "iterations": iterations,
        "history": history,
        "colours": colours,
        "weights": weights,
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
