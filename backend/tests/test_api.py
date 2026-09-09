"""
Tests for the web layer: colour helpers, response assembly and the HTTP routes.

The animation tests matter more than they look. The visualisation claims to show
the algorithm's real intermediate state, so one test here asserts it tells the
same story the analysis does -- a walkthrough that quietly disagreed with the
answer would be worse than no walkthrough at all.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.api import AnalysisError, analyse, app, explain
from app.colour import (
    describe_colour,
    hex_to_rgb,
    relative_luminance,
    rgb_to_hex,
    rgb_to_hsv,
)
from app.samples import SAMPLES, render_sample
from tests.helpers import bands, encode, solid

client = TestClient(app)

# 60% teal / 30% orange / 10% blue -- proportions checkable by hand.
KNOWN = encode(bands(((34, 148, 148), 60), ((240, 140, 30), 30), ((44, 96, 200), 10)))


# ------------------------------------------------------------- colour helpers

def test_hex_round_trip():
    assert rgb_to_hex((255, 87, 51)) == "#FF5733"
    assert hex_to_rgb("#FF5733") == (255, 87, 51)
    assert hex_to_rgb("F53") == (255, 85, 51)        # shorthand, each digit doubled


def test_bad_hex_is_rejected():
    for bad in ("#ZZZZZZ", "12345", ""):
        with pytest.raises(ValueError):
            hex_to_rgb(bad)


@pytest.mark.parametrize(
    "colour,hue", [((255, 0, 0), 0.0), ((0, 255, 0), 120.0), ((0, 0, 255), 240.0)]
)
def test_hsv_hue_of_the_primaries(colour, hue):
    measured, saturation, _value = rgb_to_hsv(colour)
    assert measured == pytest.approx(hue, abs=0.5)
    assert saturation == pytest.approx(1.0)


def test_grey_has_no_saturation():
    _hue, saturation, _value = rgb_to_hsv((128, 128, 128))
    assert saturation == pytest.approx(0.0)


def test_luminance_runs_black_to_white():
    assert relative_luminance((0, 0, 0)) == pytest.approx(0.0)
    assert relative_luminance((255, 255, 255)) == pytest.approx(1.0)


def test_colour_names_are_plausible():
    assert describe_colour((250, 250, 250)) == "White"
    assert describe_colour((5, 5, 5)) == "Black"
    assert describe_colour((220, 30, 30)) == "Red"


def test_muted_colours_are_not_all_called_grey():
    """
    Regression test.

    With only saturated primaries and neutrals in the vocabulary, every muted
    mid-tone -- which is most of a real photograph -- landed nearest to "Grey".
    """
    assert describe_colour((160, 101, 98)) != "Grey"
    assert describe_colour((130, 130, 130)) == "Grey"    # genuine neutrals still are


# ------------------------------------------------------------------- analysis

def test_known_proportions_end_to_end():
    result = analyse(KNOWN, top_n=3, max_dimension=None)
    assert result["dominant"]["rgb"] == [34, 148, 148]
    assert result["dominant"]["percentage"] == pytest.approx(60.0, abs=0.5)
    assert [c["rgb"] for c in result["palette"]] == [
        [34, 148, 148], [240, 140, 30], [44, 96, 200]
    ]


def test_both_methods_agree_on_an_obvious_image():
    histogram = analyse(KNOWN, method="histogram", max_dimension=None)
    kmeans = analyse(KNOWN, method="kmeans", top_n=3, max_dimension=None)
    assert histogram["dominant"]["rgb"] == kmeans["dominant"]["rgb"] == [34, 148, 148]


def test_kmeans_clusters_cover_the_whole_image():
    """The property that makes k-means the better answer on a colourful photo."""
    result = analyse(KNOWN, method="kmeans", top_n=3, max_dimension=None)
    assert sum(c["share"] for c in result["palette"]) == pytest.approx(1.0)


def test_jpeg_input_is_handled():
    """JPEG is lossy, so exact equality is the wrong assertion -- proximity is not."""
    result = analyse(encode(solid((34, 148, 148), 120, 120), fmt="JPEG"))
    assert all(abs(a - b) <= 6 for a, b in zip(result["dominant"]["rgb"], (34, 148, 148)))


def test_response_carries_useful_metadata():
    result = analyse(encode(solid((10, 120, 200), 200, 100)), max_dimension=None)
    assert result["image"]["width"] == 200 and result["image"]["height"] == 100
    assert result["image"]["totalPixels"] == 20000
    assert result["image"]["wasDownsampled"] is False
    assert result["stats"]["durationMs"] >= 0
    assert len(result["hueDistribution"]) == 12
    assert len(result["toneDistribution"]) == 7


def test_greyscale_image_produces_an_empty_hue_chart():
    """Grey pixels have no hue and must not be filed under red."""
    canvas = Image.new("RGB", (100, 50))
    draw = ImageDraw.Draw(canvas)
    for x in range(100):
        level = 30 + x * 2
        draw.line([(x, 0), (x, 50)], fill=(level, level, level))

    result = analyse(encode(canvas), max_dimension=None)
    assert sum(bin["count"] for bin in result["hueDistribution"]) == 0


def test_filtering_everything_is_a_clear_error():
    with pytest.raises(AnalysisError):
        analyse(encode(solid((255, 255, 255), 20, 20)), max_lightness=0.5)


def test_filter_summary_reports_what_was_removed():
    canvas = Image.new("RGB", (100, 100), (255, 255, 255))
    ImageDraw.Draw(canvas).rectangle([0, 0, 99, 29], fill=(200, 40, 60))
    result = analyse(encode(canvas), max_lightness=0.85, max_dimension=None)
    assert result["dominant"]["rgb"] == [200, 40, 60]
    assert result["filters"]["active"] is True
    assert result["filters"]["removedTooLight"] == 7000


# ------------------------------------------------------- the sample images

@pytest.mark.parametrize(
    "sample", [s for s in SAMPLES if s["expected"]], ids=lambda s: s["id"]
)
def test_samples_with_known_answers_return_them(sample):
    """
    Several demo images are built so their answer is not a matter of opinion.

    Much stronger evidence of correctness than checking a photograph and
    deciding the result looks about right.
    """
    result = analyse(render_sample(sample["id"]), max_dimension=None)
    assert tuple(result["dominant"]["rgb"]) == sample["expected"]


# ------------------------------------------------------------ the animation

def test_explanation_agrees_with_the_analysis():
    """The walkthrough must not tell a different story from the result."""
    for method in ("histogram", "kmeans"):
        analysed = analyse(KNOWN, method=method, top_n=3, max_dimension=None)
        explained = explain(KNOWN, method=method, top_n=3, max_dimension=None)
        assert explained["dominant"]["rgb"] == analysed["dominant"]["rgb"]
        assert [b["rgb"] for b in explained["buckets"]] == [
            c["rgb"] for c in analysed["palette"]
        ]


def test_animated_pixels_are_real_pixels_from_the_image():
    result = explain(KNOWN, top_n=3, max_dimension=None)
    present = {(34, 148, 148), (240, 140, 30), (44, 96, 200)}
    assert result["pixels"]
    for pixel in result["pixels"]:
        assert tuple(pixel["rgb"]) in present
        assert 0.0 <= pixel["imagePosition"][0] <= 1.0
        assert 0.0 <= pixel["imagePosition"][1] <= 1.0


def test_histogram_pixels_know_their_bucket():
    result = explain(KNOWN, bucket_size=16, top_n=3, max_dimension=None)
    assert result["iterations"] == []
    for pixel in result["pixels"]:
        assert pixel["quantisedRgb"] is not None
        assert all(channel % 16 == 0 for channel in pixel["quantisedRgb"])
        # Its bucket index must lead back to a bucket it truly belongs to.
        assert pixel["quantisedRgb"] == result["buckets"][pixel["bucket"]]["bucketRgb"]


def test_pixels_outside_the_top_n_are_marked_as_such():
    """With one bucket returned, most pixels must be flagged as 'other'."""
    result = explain(KNOWN, bucket_size=16, top_n=1, max_dimension=None)
    assert any(pixel["bucket"] == -1 for pixel in result["pixels"])
    assert any(pixel["bucket"] == 0 for pixel in result["pixels"])


def test_kmeans_records_seeds_then_rounds():
    result = explain(KNOWN, method="kmeans", top_n=3, max_dimension=None)
    assert len(result["iterations"]) >= 2
    assert result["iterations"][0]["isSeed"] is True
    assert all(step["isSeed"] is False for step in result["iterations"][1:])


def test_kmeans_shares_add_up_at_every_step():
    """Every pixel belongs to one cluster, at every point during the run."""
    result = explain(KNOWN, method="kmeans", top_n=3, max_dimension=None)
    for step in result["iterations"]:
        assert sum(centre["share"] for centre in step["centres"]) == pytest.approx(1.0)
        assert len(step["assignments"]) == result["sampleSize"]


def test_kmeans_positions_are_inside_the_plot():
    result = explain(KNOWN, method="kmeans", top_n=3, max_dimension=None)
    for pixel in result["pixels"]:
        x, y = pixel["colourPosition"]
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def test_single_colour_image_does_not_break_the_plot():
    """A flat image has no spread to scale against; it must degrade, not crash."""
    result = explain(encode(solid((90, 90, 90), 60, 60)), method="kmeans",
                     max_dimension=None)
    assert result["pixels"]
    assert all(pixel["colourPosition"] is not None for pixel in result["pixels"])


# ---------------------------------------------------------------- HTTP routes

def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_lists_and_serves_samples():
    listed = client.get("/api/samples").json()
    assert {s["id"] for s in listed} == {s["id"] for s in SAMPLES}

    response = client.get("/api/samples/blocks/image")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_analyse_sample_route():
    body = client.post("/api/samples/blocks/analyse?top_n=3").json()
    assert body["dominant"]["hex"] == "#229494"
    # The frontend expects camelCase keys.
    assert "hueDistribution" in body and "isDark" in body["dominant"]


def test_explain_sample_route():
    body = client.post("/api/samples/blocks/explain?method=kmeans&top_n=3").json()
    assert body["sampleSize"] > 0
    assert body["iterations"][0]["isSeed"] is True


def test_upload_route():
    response = client.post(
        "/api/analyse", files={"file": ("known.png", KNOWN, "image/png")},
        data={"top_n": "3"},
    )
    assert response.status_code == 200
    assert response.json()["dominant"]["hex"] == "#229494"


def test_upload_that_is_not_an_image():
    response = client.post(
        "/api/analyse", files={"file": ("notes.txt", b"not an image", "text/plain")}
    )
    assert response.status_code == 422
    assert "could not be read" in response.json()["detail"]


def test_invalid_hex_in_the_ignore_list():
    assert client.post(
        "/api/samples/blocks/analyse?ignore_colours=%23ZZZZZZ"
    ).status_code == 422


def test_contradictory_lightness_range():
    assert client.post(
        "/api/samples/blocks/analyse?min_lightness=0.9&max_lightness=0.1"
    ).status_code == 422


def test_unknown_method_is_rejected():
    """`method` is a Literal, so FastAPI validates it without an enum class."""
    assert client.post("/api/samples/blocks/analyse?method=nonsense").status_code == 422


def test_unknown_sample():
    assert client.post("/api/samples/nope/analyse").status_code == 404
