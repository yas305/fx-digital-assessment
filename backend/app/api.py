"""
The HTTP layer: routes, request validation and error handling.

Nothing here builds a response body -- that is ``report.py``'s job. This file
only deals with the web: what the URLs are, what parameters they accept, and
what status code a failure should produce.

Run it with:

    uvicorn app.api:app --reload --port 8000

Interactive API documentation is at /docs.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .colour import hex_to_rgb, rgb_to_hex
from .dominant import MAX_BUCKET_SIZE, MIN_BUCKET_SIZE, RGB, ImageLoadError
from .report import AnalysisError, Method, analyse, explain
from .samples import SAMPLES, SAMPLES_BY_ID, render_sample


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
