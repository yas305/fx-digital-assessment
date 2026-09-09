"""
Tests for the algorithm itself: loading, filtering, counting and cutting.

The valuable tests here are the ones built on images with a *known* answer --
exact proportions, a colour hidden under transparency. Asserting against a real
photograph only tells you the code produced something, not the right thing.
"""

from __future__ import annotations

import random

import pytest
from PIL import Image, ImageDraw

from app.dominant import (
    ImageLoadError,
    apply_filters,
    average_colour,
    count_colours,
    distance_squared,
    load_image,
    median_cut,
    quantise_pixel,
    sample_pixels,
    split_box,
    widest_channel,
)
from tests.helpers import bands, encode, solid


# --------------------------------------------------------------------- loading

def test_loads_a_plain_rgb_image():
    image = load_image(encode(solid((10, 20, 30))))
    assert len(image["pixels"]) == 60 * 40
    assert image["original_width"] == 60 and image["original_height"] == 40
    assert image["pixels"][0] == (10, 20, 30)


def test_greyscale_is_normalised_to_three_channels():
    image = load_image(encode(Image.new("L", (20, 20), 128)))
    assert image["pixels"][0] == (128, 128, 128)


def test_transparent_pixels_are_discarded():
    """Invisible pixels must not be able to win."""
    canvas = Image.new("RGBA", (40, 40), (0, 0, 0, 0))       # transparent black
    ImageDraw.Draw(canvas).rectangle([0, 0, 9, 39], fill=(200, 40, 60, 255))

    image = load_image(encode(canvas))
    assert image["transparent_dropped"] == 40 * 30
    assert len(image["pixels"]) == 40 * 10
    # Black covered 75% of the image but was invisible, so red must win.
    results, _ = count_colours(image["pixels"], 16, 1)
    assert results[0]["rgb"] == (200, 40, 60)


def test_rejects_things_that_are_not_images():
    with pytest.raises(ImageLoadError):
        load_image(b"this is definitely not a PNG")


def test_rejects_empty_input():
    with pytest.raises(ImageLoadError):
        load_image(b"")


def test_shrinking_caps_the_longest_edge():
    image = load_image(encode(solid((1, 2, 3), 1000, 500)), max_dimension=100)
    assert max(image["width"], image["height"]) == 100
    assert image["original_width"] == 1000     # the original size is still reported


# ---------------------------------------------------------------- quantisation

def test_quantise_rounds_down_to_the_bucket_step():
    assert quantise_pixel((250, 214, 7), 16) == (240, 208, 0)
    assert quantise_pixel((251, 215, 8), 16) == (240, 208, 0)     # the same bucket
    assert quantise_pixel((255, 255, 255), 16) == (240, 240, 240)
    assert quantise_pixel((137, 42, 9), 1) == (137, 42, 9)        # a step of 1 does nothing


# -------------------------------------------------------------------- counting

def test_counts_an_exact_majority():
    pixels = [(200, 0, 0)] * 60 + [(0, 0, 200)] * 40
    results, distinct = count_colours(pixels, bucket_size=10, top_n=2)
    assert distinct == 2
    assert results[0]["rgb"] == (200, 0, 0)
    assert results[0]["count"] == 60
    assert results[0]["share"] == pytest.approx(0.6)


def test_near_identical_shades_pool_their_votes():
    """
    The core justification for rounding.

    Ten slightly different blues against one flat white block. Counted raw, the
    white block wins. Grouped, the blues pool their votes and win.
    """
    blues = [(100, 150, 200 + offset) for offset in range(10) for _ in range(10)]
    pixels = blues + [(255, 255, 255)] * 50

    ungrouped, distinct_raw = count_colours(pixels, bucket_size=1, top_n=1)
    assert distinct_raw == 11
    assert ungrouped[0]["rgb"] == (255, 255, 255)      # white wins on raw counts

    grouped, distinct_grouped = count_colours(pixels, bucket_size=16, top_n=1)
    assert distinct_grouped < distinct_raw
    assert grouped[0]["count"] > 50                    # the pooled blues beat white
    assert grouped[0]["rgb"][2] > 190


def test_bucket_boundaries_can_split_a_colour():
    """
    Documents the known weakness of a fixed grid.

    Blue values 200-209 look identical to a person, but at a bucket size of 16
    the grid line falls at 208, so 200-207 land in one bucket and 208-209 in the
    next. The group splits 80/20 instead of pooling all 100 votes.

    This is inherent to any fixed grid, and is the main reason median cut
    exists alongside it: it draws its boundaries to fit the image rather than
    at fixed positions decided before the image was seen.
    """
    blues = [(100, 150, 200 + offset) for offset in range(10) for _ in range(10)]

    results, _ = count_colours(blues, bucket_size=16, top_n=2)
    assert [r["count"] for r in results] == [80, 20]

    # Median cut is not bound by the grid, so it keeps all 100 together.
    assert median_cut(blues, box_count=1)["results"][0]["count"] == 100


def test_reported_colour_is_the_true_average_not_the_bucket_label():
    """
    All pixels are (105, 105, 105), which rounds down to bucket (100, 100, 100).
    We must report 105 -- a colour actually present -- not the grid corner.
    """
    results, _ = count_colours([(105, 105, 105)] * 50, bucket_size=50, top_n=1)
    assert results[0]["rgb"] == (105, 105, 105)
    assert results[0]["bucket"] == (100, 100, 100)


def test_top_n_is_ordered_and_shares_add_up():
    pixels = [(10, 10, 10)] * 50 + [(100, 100, 100)] * 30 + [(200, 200, 200)] * 20
    results, _ = count_colours(pixels, bucket_size=8, top_n=3)
    assert [r["count"] for r in results] == [50, 30, 20]
    assert sum(r["share"] for r in results) == pytest.approx(1.0)


def test_asking_for_more_colours_than_exist_is_clamped():
    results, distinct = count_colours([(7, 7, 7)] * 30, bucket_size=10, top_n=10)
    assert distinct == 1 and len(results) == 1


def test_ties_are_broken_predictably():
    """
    Without an explicit tie-break the winner would depend on the order the
    pixels happened to appear in, and the same image could give two answers.
    """
    first, _ = count_colours([(200, 10, 10)] * 25 + [(10, 200, 10)] * 25, 16, 2)
    second, _ = count_colours([(10, 200, 10)] * 25 + [(200, 10, 10)] * 25, 16, 2)
    assert [r["rgb"] for r in first] == [r["rgb"] for r in second]


def test_counting_nothing():
    assert count_colours([], 16, 3) == ([], 0)


# ----------------------------------------------------------------- median cut

def test_distance_squared_examples():
    assert distance_squared((0, 0, 0), (0, 0, 0)) == 0
    assert distance_squared((3, 0, 0), (0, 4, 0)) == 25          # 3^2 + 4^2


def test_widest_channel_finds_the_most_varied():
    box = [(10, 100, 50), (20, 200, 55)]     # red spans 10, green 100, blue 5
    channel, spread = widest_channel(box)
    assert channel == 1 and spread == 100


def test_average_colour_averages_each_channel_separately():
    assert average_colour([(10, 20, 30), (20, 40, 60)]) == (15, 30, 45)


def test_split_cuts_along_the_widest_channel():
    box = [(0, 10, 5), (10, 10, 5), (250, 10, 5)]     # only red varies
    left, right = split_box(box)
    assert left == [(0, 10, 5), (10, 10, 5)]          # both below the midpoint
    assert right == [(250, 10, 5)]


def test_midpoint_split_leaves_uniform_regions_alone():
    """
    The reason we cut at the middle VALUE, not the middle PIXEL.

    Textbook median cut splits so both halves hold the same number of pixels,
    which is right for building a balanced palette but wrong for finding a
    dominant colour: it chops a large uniform region straight down the middle.
    """
    pixels = [(34, 148, 148)] * 60 + [(240, 140, 30)] * 30 + [(44, 96, 200)] * 10

    midpoint = median_cut(pixels, box_count=3)["results"]
    assert midpoint[0]["rgb"] == (34, 148, 148)
    assert midpoint[0]["share"] == pytest.approx(0.6)

    # The same data cut at the median splits the teal block in half.
    at_median = median_cut(pixels, box_count=3, at_median=True)["results"]
    assert at_median[0]["share"] < 0.6


def test_finds_obviously_separate_groups():
    pixels = [(220, 40, 40)] * 50 + [(40, 60, 200)] * 30 + [(40, 200, 60)] * 20
    run = median_cut(pixels, box_count=3)
    assert [r["count"] for r in run["results"]] == [50, 30, 20]
    assert run["results"][0]["rgb"] == (220, 40, 40)


def test_boxes_cover_every_pixel():
    """
    Every pixel is in exactly one box, so the shares total 1.

    This is the property that makes it useful on a colourful photograph, where
    the histogram's top few buckets might cover only a few percent of it.
    """
    rng = random.Random(2)
    pixels = [(rng.randrange(256), rng.randrange(256), rng.randrange(256))
              for _ in range(3000)]
    run = median_cut(pixels, box_count=6)
    assert sum(r["share"] for r in run["results"]) == pytest.approx(1.0)
    assert sum(r["count"] for r in run["results"]) == 3000


def test_is_deterministic():
    """No randomness anywhere, so the same image always gives the same answer."""
    rng = random.Random(8)
    pixels = [(rng.randrange(256), rng.randrange(256), rng.randrange(256))
              for _ in range(2000)]
    first = median_cut(pixels, box_count=4)["results"]
    second = median_cut(pixels, box_count=4)["results"]
    assert [(r["rgb"], r["count"]) for r in first] == [(r["rgb"], r["count"]) for r in second]


def test_stops_early_when_there_is_nothing_left_to_cut():
    """An image of one flat colour cannot be split, however many boxes we ask for."""
    run = median_cut([(90, 90, 90)] * 40, box_count=8)
    assert len(run["results"]) == 1
    assert run["results"][0]["count"] == 40
    assert run["splits"] == 0


def test_records_a_step_per_cut_for_the_animation():
    pixels = [(220, 40, 40)] * 50 + [(40, 60, 200)] * 30 + [(40, 200, 60)] * 20
    run = median_cut(pixels, box_count=3, record_steps=True)
    # One entry for the starting box, then one per cut.
    assert len(run["steps"]) == run["splits"] + 1
    assert len(run["steps"][0]["colours"]) == 1
    assert len(run["steps"][-1]["colours"]) == 3


def test_cutting_nothing():
    run = median_cut([], box_count=3)
    assert run["results"] == [] and run["splits"] == 0


# --------------------------------------------------------------------- filters

def test_white_filter_reveals_the_subject():
    """A crimson subject on a white background, which is the majority colour."""
    canvas = Image.new("RGB", (100, 100), (255, 255, 255))
    ImageDraw.Draw(canvas).rectangle([0, 0, 99, 29], fill=(200, 40, 60))
    pixels = load_image(encode(canvas), max_dimension=None)["pixels"]

    unfiltered, _ = count_colours(pixels, 16, 1)
    assert unfiltered[0]["rgb"] == (255, 255, 255)

    kept, removed = apply_filters(pixels, max_lightness=0.85)
    filtered, _ = count_colours(kept, 16, 1)
    assert filtered[0]["rgb"] == (200, 40, 60)
    assert removed["too_light"] == 7000


def test_saturation_filter_removes_greys():
    kept, removed = apply_filters(
        [(128, 128, 128)] * 80 + [(220, 20, 30)] * 20, min_saturation=0.2
    )
    assert len(kept) == 20
    assert removed["low_saturation"] == 80


def test_explicit_ignore_list_with_tolerance():
    kept, removed = apply_filters(
        [(255, 0, 255)] * 50 + [(0, 128, 0)] * 10,
        ignore_colours=[(250, 5, 250)], tolerance=20,
    )
    assert removed["ignored"] == 50
    assert len(kept) == 10


def test_exclusion_counts_do_not_double_count():
    """A white pixel breaks several rules; it must be counted against one only."""
    _kept, removed = apply_filters(
        [(255, 255, 255)] * 25, min_saturation=0.5, max_lightness=0.9
    )
    assert removed["total"] == 25
    assert removed["low_saturation"] + removed["too_light"] == 25


def test_no_filters_returns_everything_untouched():
    pixels = [(1, 2, 3), (4, 5, 6)]
    kept, removed = apply_filters(pixels)
    assert kept is pixels and removed["total"] == 0


# -------------------------------------------------------------------- sampling

def test_sampling_keeps_positions_inside_the_image():
    image = load_image(encode(bands(((34, 148, 148), 60), ((240, 140, 30), 40))))
    sample = sample_pixels(image, 100)
    assert len(sample) == 100
    for colour, x, y in sample:
        assert colour in {(34, 148, 148), (240, 140, 30)}
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def test_sampling_is_deterministic():
    """A visualisation that reshuffles on every run is distracting to demo."""
    image = load_image(encode(bands(((34, 148, 148), 60), ((240, 140, 30), 40))))
    assert sample_pixels(image, 50) == sample_pixels(image, 50)


def test_sampling_never_returns_transparent_pixels():
    canvas = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).rectangle([0, 0, 9, 39], fill=(200, 40, 60, 255))
    image = load_image(encode(canvas))
    assert all(colour == (200, 40, 60) for colour, _x, _y in sample_pixels(image, 50))
