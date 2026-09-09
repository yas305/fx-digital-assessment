#!/usr/bin/env python3
"""
Command-line interface for the dominant colour finder.

The brief asks for a program that takes an image file and prints the dominant
colour, so that exists here as a first-class entry point rather than only as a
web service.

It runs the same analysis the web API does -- both call `analyse` in
`app/report.py` -- but needs no web framework: the only third-party package
involved is Pillow, and only to decode the image file.

Usage:
    python cli.py photo.jpg
    python cli.py photo.jpg --top 5 --method mediancut
    python cli.py product.jpg --ignore-white
    python cli.py photo.jpg --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from bootstrap import use_the_right_python

# Must happen before anything from `app` is imported, because that is what
# needs the dependencies. Quiet, so it does not clutter the tool's output.
use_the_right_python(str(Path(__file__).resolve()), needs=("PIL",), announce=False)

from app.report import AnalysisError, analyse  # noqa: E402
from app.colour import hex_to_rgb  # noqa: E402
from app.dominant import ImageLoadError  # noqa: E402

# Escape code that returns the terminal to its normal colours.
RESET = "\033[0m"


def swatch(colour, width: int = 6) -> str:
    """A block of solid colour, drawn with a 24-bit terminal background colour."""
    red, green, blue = colour
    return f"\033[48;2;{red};{green};{blue}m{' ' * width}{RESET}"


def supports_colour() -> bool:
    """True if the output looks like a terminal that can show colour."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line interface."""
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Find the dominant colour of an image.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python cli.py photo.jpg\n"
            "  python cli.py photo.jpg --top 5\n"
            "  python cli.py logo.png --method mediancut --top 5\n"
            "  python cli.py product.jpg --ignore-white --json\n"
        ),
    )
    parser.add_argument("image", type=Path, help="Path to the image file.")
    parser.add_argument("--method", choices=["histogram", "mediancut"], default="histogram",
                        help="Counting strategy (default: histogram).")
    parser.add_argument("--top", type=int, default=1, metavar="N",
                        help="Return the top N colours instead of just one.")
    parser.add_argument("--bucket-size", type=int, default=16, metavar="STEP",
                        help="Rounding step applied to each channel (default: 16).")
    parser.add_argument("--max-dimension", type=int, default=400, metavar="PX",
                        help="Shrink so the longest edge is at most this (default: 400).")
    parser.add_argument("--full-resolution", action="store_true",
                        help="Analyse every pixel, ignoring --max-dimension.")
    parser.add_argument("--ignore-white", action="store_true", help="Exclude near-white pixels.")
    parser.add_argument("--ignore-black", action="store_true", help="Exclude near-black pixels.")
    parser.add_argument("--ignore-grey", action="store_true", help="Exclude washed-out pixels.")
    parser.add_argument("--ignore", action="append", default=[], metavar="HEX",
                        help="Exclude a specific colour, e.g. --ignore '#FF00FF'. Repeatable.")
    parser.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    return parser


def print_report(result: dict, bucket_size: int, show_palette: bool) -> None:
    """
    Print the human-readable report.

    Kept apart from :func:`main` so working out the answer and displaying it are
    not interleaved.
    """
    colour = supports_colour()
    pad = " " * (10 if colour else 0)
    dominant = result["dominant"]
    image = result["image"]
    stats = result["stats"]
    red, green, blue = dominant["rgb"]

    print()
    print(f"  {image['filename']}  --  {image['width']}x{image['height']} {image['format']}")
    print(f"  {'-' * 58}")
    print()
    print("  DOMINANT COLOUR")
    print(f"    {swatch(dominant['rgb'], 10) if colour else ''}  RGB({red}, {green}, {blue})")
    print(f"    {pad}  {dominant['hex']}  ~{dominant['name']}")
    print(f"    {pad}  {dominant['percentage']}% of pixels counted")
    print()

    if show_palette:
        print(f"  TOP {len(result['palette'])} COLOURS")
        for position, entry in enumerate(result["palette"], start=1):
            bar = "#" * max(1, round(entry["share"] * 28))
            print(f"    {position:>2}. {swatch(entry['rgb']) if colour else ''} "
                  f"{entry['hex']}  {entry['percentage']:>5.2f}%  {bar}  {entry['name']}")
        print()

    print("  DETAIL")
    print(f"    method              {result['method']}")
    if stats["iterations"] is not None:
        print(f"    cuts made           {stats['iterations']}")
    else:
        print(f"    bucket size         {bucket_size}")
    print(f"    pixels counted      {result['filters']['pixelsCounted']:,} "
          f"of {image['totalPixels']:,}")
    print(f"    exact colours       {stats['uniqueRawColours']:,}")
    print(f"    groups after merge  {stats['distinctColours']:,}")
    if result["filters"]["totalRemoved"]:
        print(f"    pixels excluded     {result['filters']['totalRemoved']:,}")
    if image["transparentDropped"]:
        print(f"    transparent dropped {image['transparentDropped']:,}")
    print(f"    took                {stats['durationMs']:.1f} ms")
    print()


def main(argv: Optional[List[str]] = None) -> int:
    """
    Read the arguments, analyse the image, print the result.

    Returns the process exit code: 0 on success, 1 if the image could not be
    analysed, 2 if the path given is not a readable file.
    """
    args = build_parser().parse_args(argv)

    if not args.image.is_file():
        print(f"error: no such file: {args.image}", file=sys.stderr)
        return 2

    try:
        unwanted = [hex_to_rgb(value) for value in args.ignore]
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        result = analyse(
            args.image.read_bytes(),
            method=args.method,
            bucket_size=args.bucket_size,
            top_n=max(args.top, 1),
            max_dimension=None if args.full_resolution else args.max_dimension,
            # 0.85 rather than 1.0 so "near-white" catches off-whites and paper
            # textures too, which is what people mean by a white background.
            max_lightness=0.85 if args.ignore_white else 1.0,
            min_lightness=0.15 if args.ignore_black else 0.0,
            min_saturation=0.15 if args.ignore_grey else 0.0,
            ignore_colours=unwanted,
            filename=args.image.name,
        )
    except (ImageLoadError, AnalysisError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: could not read {args.image}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result, args.bucket_size, show_palette=args.top > 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
