"""
The web layer: building the JSON response and serving it over HTTP.

Everything here is presentation. The algorithm lives in ``dominant.py`` and
knows nothing about HTTP or JSON.

There are no classes and no schema objects. Each response is a plain dictionary
built by a named function, with the JSON keys written out literally -- so to know
what the frontend receives, read the dictionary. Keys are camelCase because that
is what reads naturally in TypeScript.

Run it with:

    uvicorn app.api:app --reload --port 8000

Interactive API documentation is at /docs.
"""

from __future__ import annotations

import time
from typing import List, Literal, Optional, Sequence, Tuple

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .colour import (
    describe_colour,
    hex_to_rgb,
    hsv_to_rgb,
    relative_luminance,
    rgb_to_hex,
    rgb_to_hsv,
)
from .dominant import (
    DEFAULT_SAMPLE_SIZE,
    MAX_BUCKET_SIZE,
    MIN_BUCKET_SIZE,
    RGB,
    ImageLoadError,
    apply_filters,
    count_colours,
    load_image,
    median_cut,
    quantise_pixel,
    sample_pixels,
)
from .samples import SAMPLES, SAMPLES_BY_ID, render_sample

# The two counting strategies. A plain string rather than an enum class --
# FastAPI validates it just the same and rejects anything else with a 422.
Method = Literal["histogram", "mediancut"]


class AnalysisError(ValueError):
    """Analysis could not produce a result from this image and these settings."""


# ===========================================================================
#  Building the response
# ===========================================================================

# Twelve 30-degree slices of the hue wheel: enough to tell orange from yellow,
# few enough that every bar in the chart stays readable.
HUE_LABELS = ["Red", "Orange", "Yellow", "Chartreuse", "Green", "Spring",
              "Cyan", "Azure", "Blue", "Violet", "Magenta", "Rose"]

TONE_LABELS = ["Darkest", "Dark", "Mid-dark", "Mid", "Mid-light", "Light", "Lightest"]

# Below this saturation a pixel has no meaningful hue, so it is left out of the
# hue chart rather than filed under "Red" -- which is what hue 0 means, and what
# every grey pixel would otherwise be recorded as.
HUE_CHART_MIN_SATURATION = 0.12


def describe_result(colour: dict) -> dict:
    """Add the extra fields the frontend displays to one counted colour."""
    luminance = relative_luminance(colour["rgb"])
    return {
        "rgb": list(colour["rgb"]),
        "hex": rgb_to_hex(colour["rgb"]),
        "name": describe_colour(colour["rgb"]),
        "count": colour["count"],
        "share": colour["share"],
        "percentage": round(colour["share"] * 100, 2),
        "luminance": round(luminance, 4),
        # 0.4 rather than 0.5: mid-tones read better with white text on them.
        "isDark": luminance < 0.4,
        "bucketRgb": list(colour["bucket"]),
    }


def build_charts(pixels: List[RGB]) -> dict:
    """
    Build both distribution charts and the summary averages, in one pass.

    One pass rather than three because converting every pixel to HSV is the most
    expensive thing the analysis does, so it is worth doing only once.
    """
    hue_counts = [0] * 12
    tone_counts = [0] * len(TONE_LABELS)
    saturation_total = lightness_total = 0.0
    colourful_pixels = 0

    for pixel in pixels:
        hue, saturation, lightness = rgb_to_hsv(pixel)
        saturation_total += saturation
        lightness_total += lightness

        # min() guards the exact value 1.0, which would index past the end.
        tone_counts[min(int(lightness * len(TONE_LABELS)), len(TONE_LABELS) - 1)] += 1

        if saturation >= HUE_CHART_MIN_SATURATION and lightness > 0.06:
            hue_counts[min(int(hue / 30.0), 11)] += 1
            colourful_pixels += 1

    total = len(pixels)
    hue_total = sum(hue_counts)

    hue_bins = [
        {
            "label": label,
            "startDegrees": index * 30.0,
            "endDegrees": index * 30.0 + 30.0,
            "count": hue_counts[index],
            "share": (hue_counts[index] / hue_total) if hue_total else 0.0,
            # A fully saturated sample of this slice, to colour the bar.
            "hex": rgb_to_hex(hsv_to_rgb(index * 30.0 + 15.0, 1.0, 1.0)),
        }
        for index, label in enumerate(HUE_LABELS)
    ]

    tone_bins = []
    for index, label in enumerate(TONE_LABELS):
        # The midpoint grey of this band, as the bar's colour.
        level = round(((index + 0.5) / len(TONE_LABELS)) * 255)
        tone_bins.append(
            {
                "label": label,
                "count": tone_counts[index],
                "share": (tone_counts[index] / total) if total else 0.0,
                "hex": rgb_to_hex((level, level, level)),
            }
        )

    average_saturation = saturation_total / total if total else 0.0
    average_lightness = lightness_total / total if total else 0.0

    # A rough 0-1 measure of variety: how vivid the image is, combined with how
    # much of the hue wheel it occupies. A grey wall scores near 0, a box of
    # crayons near 1. Purely descriptive -- it never affects the answer.
    if colourful_pixels:
        occupied = sum(1 for count in hue_counts if count > 0) / 12.0
        colourfulness = min(1.0, average_saturation * 0.6 + occupied * 0.4)
    else:
        colourfulness = average_saturation * 0.5

    return {
        "hue": hue_bins,
        "tone": tone_bins,
        "averageSaturation": round(average_saturation, 4),
        "averageLightness": round(average_lightness, 4),
        "colourfulness": round(colourfulness, 4),
    }


def describe_image(image: dict, data: bytes, filename: Optional[str]) -> dict:
    """Describe where the analysed image came from."""
    return {
        "filename": filename,
        "format": image["format"],
        "mode": image["mode"],
        "width": image["original_width"],
        "height": image["original_height"],
        "totalPixels": image["original_width"] * image["original_height"],
        "sampledWidth": image["width"],
        "sampledHeight": image["height"],
        "sampledPixels": len(image["pixels"]),
        "wasDownsampled": (image["width"], image["height"])
        != (image["original_width"], image["original_height"]),
        "transparentDropped": image["transparent_dropped"],
        "fileSizeBytes": len(data),
    }


def load_and_filter(
    data: bytes,
    max_dimension: Optional[int],
    min_saturation: float,
    min_lightness: float,
    max_lightness: float,
    ignore_colours: Sequence[RGB],
    tolerance: int,
) -> Tuple[dict, List[RGB], dict]:
    """
    The shared front half of both endpoints: decode, then apply the exclusions.

    Returns ``(image, kept_pixels, removed_counts)``.
    """
    image = load_image(data, max_dimension=max_dimension)
    kept, removed = apply_filters(
        image["pixels"],
        min_saturation=min_saturation,
        min_lightness=min_lightness,
        max_lightness=max_lightness,
        ignore_colours=ignore_colours,
        tolerance=tolerance,
    )
    if not kept:
        raise AnalysisError(
            "Those filters excluded every pixel in the image. Try relaxing them."
        )
    return image, kept, removed


def analyse(
    data: bytes,
    method: Method = "histogram",
    bucket_size: int = 16,
    top_n: int = 6,
    max_dimension: Optional[int] = 400,
    min_saturation: float = 0.0,
    min_lightness: float = 0.0,
    max_lightness: float = 1.0,
    ignore_colours: Sequence[RGB] = (),
    tolerance: int = 24,
    filename: Optional[str] = None,
) -> dict:
    """
    Run the whole pipeline over raw image bytes and package the result as JSON.

    Raises:
        ImageLoadError: if the bytes are not a decodable image.
        AnalysisError: if filtering removed every pixel.
    """
    started = time.perf_counter()

    image, counted, removed = load_and_filter(
        data, max_dimension, min_saturation, min_lightness, max_lightness,
        ignore_colours, tolerance,
    )

    # How many exact colours the image holds, before any grouping. Shown next to
    # the grouped count to make the effect of rounding visible.
    unique_raw = len(set(image["pixels"]))

    iterations = None
    if method == "mediancut":
        run = median_cut(counted, box_count=max(top_n, 1))
        colours, distinct = run["results"], len(run["results"])
        iterations = run["splits"]
    else:
        colours, distinct = count_colours(counted, bucket_size=bucket_size, top_n=top_n)

    if not colours:
        raise AnalysisError("No colours could be counted in that image.")

    charts = build_charts(counted)
    palette = [describe_result(colour) for colour in colours]

    return {
        "method": method,
        "dominant": palette[0],
        "palette": palette,
        "hueDistribution": charts["hue"],
        "toneDistribution": charts["tone"],
        "image": describe_image(image, data, filename),
        "filters": {
            "active": removed["total"] > 0 or any(
                [min_saturation > 0, min_lightness > 0, max_lightness < 1, bool(ignore_colours)]
            ),
            "removedLowSaturation": removed["low_saturation"],
            "removedTooDark": removed["too_dark"],
            "removedTooLight": removed["too_light"],
            "removedIgnored": removed["ignored"],
            "totalRemoved": removed["total"],
            "pixelsCounted": len(counted),
        },
        "stats": {
            "distinctColours": distinct,
            "uniqueRawColours": unique_raw,
            "averageSaturation": charts["averageSaturation"],
            "averageLightness": charts["averageLightness"],
            "colourfulness": charts["colourfulness"],
            "iterations": iterations,
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
        },
        "optionsUsed": {
            "method": method,
            "bucketSize": bucket_size,
            "topN": top_n,
            "maxDimension": max_dimension,
            "minSaturation": min_saturation,
            "minLightness": min_lightness,
            "maxLightness": max_lightness,
            "ignoreColours": [rgb_to_hex(colour) for colour in ignore_colours],
            "ignoreTolerance": tolerance,
        },
    }


# ===========================================================================
#  The algorithm animation
#
#  The frontend replays the algorithm's genuine intermediate state rather than
#  an illustration of it, so this returns real sampled pixels and, for median
#  cut, the colour of every box after every cut.
# ===========================================================================


def choose_plot_axes(colours: Sequence[RGB]) -> Tuple[int, int]:
    """
    Choose which two of red, green and blue to plot the scatter against.

    Colour is three-dimensional and a screen is two, so a scatter plot has to
    drop something. Rather than always dropping blue, this picks the two channels
    that vary most in *this* image -- the view most likely to show the groupings
    median cut is working with.
    """
    if not colours:
        return 0, 1

    spreads = [
        max(colour[channel] for colour in colours)
        - min(colour[channel] for colour in colours)
        for channel in range(3)
    ]
    widest, second = sorted(range(3), key=lambda channel: -spreads[channel])[:2]
    return widest, second


def plot_positions(colours: Sequence[RGB], axes: Tuple[int, int]) -> List[List[float]]:
    """
    Place colours on the plot, scaled so they fill it.

    Each axis is stretched independently to use the full width and height. That
    distorts the picture -- on-screen distance shows which colours group together
    rather than how far apart they truly are -- but the alternative squeezes
    everything into a corner whenever one colour sits far from the rest, and a
    picture where no structure is visible teaches nothing.
    """
    if not colours:
        return []

    ranges = []
    for channel in axes:
        low = min(colour[channel] for colour in colours)
        high = max(colour[channel] for colour in colours)
        ranges.append((low, max(high - low, 1)))

    return [
        [
            (colour[axes[0]] - ranges[0][0]) / ranges[0][1],
            (colour[axes[1]] - ranges[1][0]) / ranges[1][1],
        ]
        for colour in colours
    ]


def explain(
    data: bytes,
    method: Method = "histogram",
    bucket_size: int = 16,
    top_n: int = 6,
    max_dimension: Optional[int] = 400,
    min_saturation: float = 0.0,
    min_lightness: float = 0.0,
    max_lightness: float = 1.0,
    filename: Optional[str] = None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> dict:
    """
    Produce the step-by-step data behind the algorithm animation.

    Deliberately runs the same pipeline as :func:`analyse` rather than a
    simplified stand-in, so the animation is a window onto the real algorithm
    rather than a re-enactment of it.
    """
    image, counted, _removed = load_and_filter(
        data, max_dimension, min_saturation, min_lightness, max_lightness, (), 24
    )

    # The sample comes from the whole image, not the filtered set: the animation
    # is more informative when excluded pixels can be seen being set aside than
    # when they never appear at all.
    sample = sample_pixels(image, sample_size)
    sample_colours = [colour for colour, _x, _y in sample]

    iterations: List[dict] = []
    positions = None
    quantised = None

    if method == "mediancut":
        run = median_cut(counted, box_count=max(top_n, 1), record_steps=True)
        ranked, distinct = run["results"], len(run["results"])

        axes = choose_plot_axes(sample_colours)
        positions = plot_positions(sample_colours, axes)

        # A box's position in the list is arbitrary, but its rank (biggest
        # first) is what the palette beside the animation is ordered by.
        final = run["steps"][-1]
        rank_of = {
            index: rank
            for rank, index in enumerate(
                sorted(
                    range(len(final["colours"])),
                    key=lambda i: -sum(
                        1 for box in final["lookup"].values() if box == i
                    ),
                )
            )
        }

        total_pixels = len(counted) or 1
        for step_number, step in enumerate(run["steps"]):
            colours_now = step["colours"]
            lookup = step["lookup"]

            share_of = [0] * len(colours_now)
            for colour in counted:
                box = lookup.get(colour)
                if box is not None and box < len(share_of):
                    share_of[box] += 1

            box_positions = plot_positions(colours_now, axes)
            iterations.append(
                {
                    "step": step_number,
                    # Step 0 is the single starting box, before any cut.
                    "isFirst": step_number == 0,
                    "boxes": [
                        {
                            "rgb": list(colours_now[index]),
                            "hex": rgb_to_hex(colours_now[index]),
                            "position": box_positions[index],
                            "rank": rank_of.get(index, index),
                            "share": share_of[index] / total_pixels,
                        }
                        for index in range(len(colours_now))
                    ],
                    "assignments": [
                        lookup.get(colour, 0) for colour in sample_colours
                    ],
                }
            )

        bucket_of_pixel = [
            rank_of.get(final["lookup"].get(colour, -1), -1) for colour in sample_colours
        ]
    else:
        ranked, distinct = count_colours(counted, bucket_size=bucket_size, top_n=top_n)
        quantised = [quantise_pixel(colour, bucket_size) for colour in sample_colours]

        # Which of the returned buckets each sampled pixel belongs to, or -1 for
        # those outside the top N -- the animation's "other" column.
        rank_of_bucket = {colour["bucket"]: index for index, colour in enumerate(ranked)}
        bucket_of_pixel = [rank_of_bucket.get(bucket, -1) for bucket in quantised]

    if not ranked:
        raise AnalysisError("No colours could be counted in that image.")

    pixels = [
        {
            "rgb": list(colour),
            "hex": rgb_to_hex(colour),
            "quantisedRgb": list(quantised[index]) if quantised else None,
            "quantisedHex": rgb_to_hex(quantised[index]) if quantised else None,
            "imagePosition": [sample[index][1], sample[index][2]],
            "colourPosition": positions[index] if positions else None,
            "bucket": bucket_of_pixel[index],
        }
        for index, colour in enumerate(sample_colours)
    ]

    return {
        "method": method,
        "bucketSize": bucket_size,
        "sampleSize": len(pixels),
        "totalPixels": len(counted),
        "uniqueRawColours": len(set(image["pixels"])),
        "distinctColours": distinct,
        "pixels": pixels,
        "buckets": [
            {
                "rgb": list(colour["rgb"]),
                "hex": rgb_to_hex(colour["rgb"]),
                "name": describe_colour(colour["rgb"]),
                "bucketRgb": list(colour["bucket"]),
                "bucketHex": rgb_to_hex(colour["bucket"]),
                "count": colour["count"],
                "share": colour["share"],
                "percentage": round(colour["share"] * 100, 2),
            }
            for colour in ranked
        ],
        "iterations": iterations,
        "dominant": describe_result(ranked[0]),
        "image": describe_image(image, data, filename),
    }


# ===========================================================================
#  HTTP routes
# ===========================================================================

# Uploads larger than this are rejected before decoding: generous for a
# photograph, small enough that a huge upload cannot exhaust memory.
MAX_UPLOAD_BYTES = 12 * 1024 * 1024

app = FastAPI(
    title="Dominant Colour Finder",
    description=(
        "Finds the most frequent colour in an image, using either a rounded "
        "histogram or median cut."
    ),
    version="1.0.0",
)

# The Vite dev server runs on a different port, so the browser treats API calls
# as cross-origin. Development origins only; a deployment would name the real
# frontend domain here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def parse_ignore_list(raw: Optional[str]) -> List[RGB]:
    """Parse a comma-separated list of hex colours, e.g. '#FFFFFF,#000'."""
    if not raw or not raw.strip():
        return []

    colours = []
    for chunk in raw.split(","):
        if chunk.strip():
            try:
                colours.append(hex_to_rgb(chunk))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    return colours


def check_lightness_range(min_lightness: float, max_lightness: float) -> None:
    """Reject a filter range that would exclude everything by definition."""
    if min_lightness > max_lightness:
        raise HTTPException(
            status_code=422,
            detail="The minimum lightness filter cannot be above the maximum.",
        )


def run(work) -> dict:
    """
    Call an analysis, turning its errors into sensible HTTP responses.

    A bad upload is the caller's problem, not a server fault, so both failure
    modes become a 422 rather than a 500 with a stack trace.
    """
    try:
        return work()
    except (ImageLoadError, AnalysisError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def find_sample(sample_id: str) -> None:
    """404 if there is no sample by that name."""
    if sample_id not in SAMPLES_BY_ID:
        raise HTTPException(status_code=404, detail=f"No sample named '{sample_id}'.")


async def read_upload(file: UploadFile) -> bytes:
    """Read an upload, rejecting anything above the size limit."""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"That file is {len(data) / 1_048_576:.1f} MB. "
                f"The limit is {MAX_UPLOAD_BYTES // 1_048_576} MB."
            ),
        )
    return data


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """Liveness check, used by the frontend to show connection status."""
    return {"status": "ok"}


@app.get("/api/samples", tags=["samples"])
def list_samples() -> List[dict]:
    """List the bundled demo images."""
    return [
        {
            "id": sample["id"],
            "name": sample["name"],
            "description": sample["description"],
            "url": f"/api/samples/{sample['id']}/image",
        }
        for sample in SAMPLES
    ]


@app.get("/api/samples/{sample_id}/image", tags=["samples"])
def sample_image(sample_id: str) -> Response:
    """Serve a generated demo image as a PNG."""
    find_sample(sample_id)
    return Response(
        content=render_sample(sample_id),
        media_type="image/png",
        # Samples are deterministic, so they cache aggressively.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/samples/{sample_id}/analyse", tags=["analysis"])
def analyse_sample(
    sample_id: str,
    method: Method = Query("histogram"),
    bucket_size: int = Query(16, ge=MIN_BUCKET_SIZE, le=MAX_BUCKET_SIZE),
    top_n: int = Query(6, ge=1, le=24),
    max_dimension: Optional[int] = Query(400, ge=32, le=4000),
    min_saturation: float = Query(0.0, ge=0.0, le=1.0),
    min_lightness: float = Query(0.0, ge=0.0, le=1.0),
    max_lightness: float = Query(1.0, ge=0.0, le=1.0),
    ignore_colours: Optional[str] = Query(None),
    ignore_tolerance: int = Query(24, ge=0, le=128),
) -> dict:
    """Analyse one of the bundled demo images."""
    find_sample(sample_id)
    check_lightness_range(min_lightness, max_lightness)
    unwanted = parse_ignore_list(ignore_colours)

    return run(lambda: analyse(
        render_sample(sample_id), method=method, bucket_size=bucket_size, top_n=top_n,
        max_dimension=max_dimension, min_saturation=min_saturation,
        min_lightness=min_lightness, max_lightness=max_lightness,
        ignore_colours=unwanted, tolerance=ignore_tolerance,
        filename=f"{sample_id}.png",
    ))


@app.post("/api/samples/{sample_id}/explain", tags=["analysis"])
def explain_sample(
    sample_id: str,
    method: Method = Query("histogram"),
    bucket_size: int = Query(16, ge=MIN_BUCKET_SIZE, le=MAX_BUCKET_SIZE),
    top_n: int = Query(6, ge=1, le=12),
    max_dimension: Optional[int] = Query(400, ge=32, le=4000),
    min_saturation: float = Query(0.0, ge=0.0, le=1.0),
    min_lightness: float = Query(0.0, ge=0.0, le=1.0),
    max_lightness: float = Query(1.0, ge=0.0, le=1.0),
) -> dict:
    """Step-by-step data for animating the algorithm over a bundled sample."""
    find_sample(sample_id)
    check_lightness_range(min_lightness, max_lightness)

    return run(lambda: explain(
        render_sample(sample_id), method=method, bucket_size=bucket_size, top_n=top_n,
        max_dimension=max_dimension, min_saturation=min_saturation,
        min_lightness=min_lightness, max_lightness=max_lightness,
        filename=f"{sample_id}.png",
    ))


@app.post("/api/analyse", tags=["analysis"])
async def analyse_upload(
    file: UploadFile = File(..., description="The image to analyse."),
    method: Method = Form("histogram"),
    bucket_size: int = Form(16, ge=MIN_BUCKET_SIZE, le=MAX_BUCKET_SIZE),
    top_n: int = Form(6, ge=1, le=24),
    max_dimension: Optional[int] = Form(400, ge=32, le=4000),
    min_saturation: float = Form(0.0, ge=0.0, le=1.0),
    min_lightness: float = Form(0.0, ge=0.0, le=1.0),
    max_lightness: float = Form(1.0, ge=0.0, le=1.0),
    ignore_colours: Optional[str] = Form(None),
    ignore_tolerance: int = Form(24, ge=0, le=128),
) -> dict:
    """
    Analyse an uploaded image and return its dominant colour.

    ``method`` chooses between the rounded histogram and median cut. The
    rest tune how coarsely colours are grouped, how many to return, and which to
    leave out.
    """
    data = await read_upload(file)
    check_lightness_range(min_lightness, max_lightness)
    unwanted = parse_ignore_list(ignore_colours)

    return run(lambda: analyse(
        data, method=method, bucket_size=bucket_size, top_n=top_n,
        max_dimension=max_dimension, min_saturation=min_saturation,
        min_lightness=min_lightness, max_lightness=max_lightness,
        ignore_colours=unwanted, tolerance=ignore_tolerance, filename=file.filename,
    ))


@app.post("/api/explain", tags=["analysis"])
async def explain_upload(
    file: UploadFile = File(..., description="The image to visualise."),
    method: Method = Form("histogram"),
    bucket_size: int = Form(16, ge=MIN_BUCKET_SIZE, le=MAX_BUCKET_SIZE),
    top_n: int = Form(6, ge=1, le=12),
    max_dimension: Optional[int] = Form(400, ge=32, le=4000),
    min_saturation: float = Form(0.0, ge=0.0, le=1.0),
    min_lightness: float = Form(0.0, ge=0.0, le=1.0),
    max_lightness: float = Form(1.0, ge=0.0, le=1.0),
) -> dict:
    """Step-by-step data for animating the algorithm over an uploaded image."""
    data = await read_upload(file)
    check_lightness_range(min_lightness, max_lightness)

    return run(lambda: explain(
        data, method=method, bucket_size=bucket_size, top_n=top_n,
        max_dimension=max_dimension, min_saturation=min_saturation,
        min_lightness=min_lightness, max_lightness=max_lightness,
        filename=file.filename,
    ))
