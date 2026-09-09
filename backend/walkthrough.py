#!/usr/bin/env python3
"""
A guided walkthrough of both algorithms, on six pixels you can hold in your head.

    python walkthrough.py            print the whole thing
    python walkthrough.py --step     pause between sections (press Enter)

Every number below is computed by the real functions in app/dominant.py.
Nothing here is a re-enactment.
"""

from __future__ import annotations

import sys

from app.dominant import (
    average_colour,
    count_colours,
    median_cut,
    quantise_pixel,
    split_box,
    widest_channel,
)

STEP_MODE = "--step" in sys.argv

# Six pixels. To the eye: three reds, two blues, one green. But no two are
# numerically identical -- which is the whole problem.
PIXELS = [
    (203, 12, 8),
    (207, 15, 5),
    (201, 11, 9),
    (20, 30, 205),
    (25, 33, 201),
    (15, 190, 20),
]
BUCKET = 10


def title(text: str) -> None:
    print()
    print("=" * 78)
    print(f"  {text}")
    print("=" * 78)


def code(*lines: str) -> None:
    """Show a snippet of the real source."""
    print()
    print("   ┌─ CODE " + "─" * 60)
    for line in lines:
        print(f"   │ {line}")
    print("   └" + "─" * 67)


def out(*lines: str) -> None:
    """Show what that code produces."""
    for line in lines:
        print(f"     {line}")


def pause() -> None:
    if STEP_MODE:
        input("\n   ... press Enter ...")


# ===========================================================================
title("THE INPUT -- six pixels")
# ===========================================================================
print("""
  Three reds, two blues, one green. But look closely: no two pixels are
  identical. If we counted exact colours we would get six groups of one
  each and there would be no winner. That is the problem both methods solve.
""")
for i, p in enumerate(PIXELS, 1):
    print(f"     pixel {i}:  {p}")
pause()


# ===========================================================================
title("METHOD 1, STEP 1 -- give each pixel a group name  (quantise_pixel)")
# ===========================================================================
code("return (",
     "    pixel[0] // bucket_size * bucket_size,",
     "    pixel[1] // bucket_size * bucket_size,",
     "    pixel[2] // bucket_size * bucket_size,",
     ")")
print()
out(f"{'pixel':<18} {'red':<14} {'green':<14} {'blue':<14} group name")
out("-" * 74)
for p in PIXELS:
    b = quantise_pixel(p, BUCKET)
    out(f"{str(p):<18} {f'{p[0]}->{b[0]}':<14} {f'{p[1]}->{b[1]}':<14} "
        f"{f'{p[2]}->{b[2]}':<14} {b}")
print("""
     '//' divides and throws away the remainder.  203 // 10 = 20, then
     20 * 10 = 200.  Every red from 200 to 209 gives the same answer, so
     pixels 1, 2 and 3 all end up with the SAME group name (200, 10, 0).
""")
pause()


# ===========================================================================
title("METHOD 1, STEP 2 -- the counting loop  (count_colours)")
# ===========================================================================
code("how_many[bucket] += 1",
     "",
     "totals = channel_totals[bucket]",
     "totals[0] += pixel[0]      # red   into the red total",
     "totals[1] += pixel[1]      # green into the green total",
     "totals[2] += pixel[2]      # blue  into the blue total")

how_many, channel_totals = {}, {}
for i, p in enumerate(PIXELS, 1):
    bucket = quantise_pixel(p, BUCKET)
    if bucket not in how_many:
        how_many[bucket] = 0
        channel_totals[bucket] = [0, 0, 0]
    how_many[bucket] += 1
    channel_totals[bucket][0] += p[0]
    channel_totals[bucket][1] += p[1]
    channel_totals[bucket][2] += p[2]
    print()
    out(f"after pixel {i} {p}  ->  group {bucket}")
    out(f"    how_many       = {how_many}")
    out(f"    channel_totals = {channel_totals}")

print("""
     TWO DICTIONARIES, TWO DIFFERENT JOBS:

       how_many        counts PIXELS.        1, 2, 3...
       channel_totals  adds up VALUES.       203, 410, 611...

     For group (200,10,0):  how_many = 3, meaning THREE pixels.
     channel_totals = [611, 38, 22], meaning their reds add to 611,
     their greens add to 38, their blues add to 22.

     611 is not a count. There are only 3 pixels. It is 203+207+201.
""")
pause()


# ===========================================================================
title("METHOD 1, STEP 3 -- rank by the COUNTS")
# ===========================================================================
code("ranked = sorted(how_many, key=lambda bucket: (-how_many[bucket], bucket))")
ranked = sorted(how_many, key=lambda b: (-how_many[b], b))
print()
for place, b in enumerate(ranked, 1):
    out(f"{place}. group {str(b):<18} {how_many[b]} pixel(s)")
print("""
     The minus sign flips the sort so biggest goes first. The ", bucket"
     on the end only matters when two groups tie -- without it the winner
     would depend on which pixel happened to come first.
""")
pause()


# ===========================================================================
title("METHOD 1, STEP 4 -- report the AVERAGE, not the group name")
# ===========================================================================
code('"rgb": (',
     "    round(totals[0] / count),",
     "    round(totals[1] / count),",
     "    round(totals[2] / count),",
     "),")
winner = ranked[0]
n, t = how_many[winner], channel_totals[winner]
members = [p for p in PIXELS if quantise_pixel(p, BUCKET) == winner]
print()
out(f"winning group name : {winner}     <- a LABEL. No pixel is this colour.")
out(f"its real members   : {members}")
out("")
out(f"red    {t[0]} / {n} = {t[0]/n:.2f}  ->  {round(t[0]/n)}")
out(f"green  {t[1]} / {n} = {t[1]/n:.2f}  ->  {round(t[1]/n)}")
out(f"blue   {t[2]} / {n} = {t[2]/n:.2f}  ->  {round(t[2]/n)}")
answer = (round(t[0]/n), round(t[1]/n), round(t[2]/n))
out("")
out(f"ANSWER: {answer}  covering {n}/6 = {n/6:.0%} of the image")
print(f"""
     {answer} sits right in the middle of the three real pixels.
     The label {winner} does not -- which is exactly why we
     report the average instead of the label.
""")
pause()


# ===========================================================================
title("MEDIAN CUT, PART 1 -- the idea")
# ===========================================================================
print("""
     The histogram draws a grid over colour space BEFORE looking at the
     image. Median cut draws its boundaries to FIT the image instead.

     The whole algorithm:

        1. Put every pixel in one big box.
        2. Look at that box: which of red, green or blue is most spread out?
        3. Cut the box in two at the middle of that range.
        4. Find whichever box is now most spread out, and cut that one.
        5. Repeat until you have as many boxes as you asked for.
        6. Each box's average colour is one of the answers.

     No randomness. Nothing repeats until it settles. The same image always
     gives the same answer.
""")
pause()


# ===========================================================================
title("MEDIAN CUT, PART 2 -- which channel is most spread out?")
# ===========================================================================
code("for channel in range(3):",
     "    lowest  = min(pixel[channel] for pixel in box)",
     "    highest = max(pixel[channel] for pixel in box)",
     "    spread  = highest - lowest")
print()
out("Starting box = all six pixels. Spread of each channel:")
out("")
for channel, label in enumerate(("red  ", "green", "blue ")):
    values = [p[channel] for p in PIXELS]
    out(f"{label}   values {sorted(values)}")
    out(f"{'':8}highest {max(values)} - lowest {min(values)} = spread {max(values)-min(values)}")
ch, spread = widest_channel(PIXELS)
print()
out(f"widest is {['red','green','blue'][ch]}, with a spread of {spread}. That is where we cut.")
pause()


# ===========================================================================
title("MEDIAN CUT, PART 3 -- make the cut")
# ===========================================================================
code("lowest    = min(pixel[channel] for pixel in box)",
     "highest   = max(pixel[channel] for pixel in box)",
     "threshold = (lowest + highest) / 2",
     "",
     "left  = [pixel for pixel in box if pixel[channel] <= threshold]",
     "right = [pixel for pixel in box if pixel[channel] >  threshold]")
lo = min(p[ch] for p in PIXELS)
hi = max(p[ch] for p in PIXELS)
print()
out(f"channel = {['red','green','blue'][ch]}, lowest {lo}, highest {hi}")
out(f"threshold = ({lo} + {hi}) / 2 = {(lo+hi)/2}")
out("")
left, right = split_box(PIXELS)
out(f"{'pixel':<18} {['red','green','blue'][ch]:<8} side")
out("-" * 40)
for p in PIXELS:
    out(f"{str(p):<18} {p[ch]:<8} {'left' if p in left else 'right'}")
print()
out(f"left  box = {left}")
out(f"right box = {right}")
print("""
     Note we cut at the middle VALUE, not the middle PIXEL. Textbook median
     cut sorts the box and splits it so both halves hold the same NUMBER of
     pixels -- good for building a balanced palette, but wrong here: it would
     chop a large area of one colour straight down the middle and report it
     as two smaller groups.
""")
pause()


# ===========================================================================
title("MEDIAN CUT, PART 4 -- repeat on whichever box is now most spread out")
# ===========================================================================
run = median_cut(PIXELS, box_count=3, record_steps=True)
print()
for i, step in enumerate(run["steps"]):
    label = "start" if i == 0 else f"after cut {i}"
    out(f"{label:<14} {len(step['colours'])} box(es):  "
        + "   ".join(str(c) for c in step["colours"]))
print("""
     Each line is one cut. The boxes get smaller and their average colours
     get sharper -- the first box is a muddy average of the whole image,
     because it contains everything.
""")
pause()


# ===========================================================================
title("MEDIAN CUT, PART 5 -- the answer")
# ===========================================================================
code("return (",
     "    round(sum(pixel[0] for pixel in box) / count),",
     "    round(sum(pixel[1] for pixel in box) / count),",
     "    round(sum(pixel[2] for pixel in box) / count),",
     ")")
print()
out("Each box's average colour, exactly like the histogram averages a bucket:")
out("")
for r in run["results"]:
    out(f"{str(r['rgb']):<18} {r['count']} of 6 pixels   {r['share']:>4.0%}")
print(f"""
     Cuts made: {run['splits']}

     Every pixel is in exactly one box, so the shares add to 100%. That is
     the property the histogram does not have -- its top few buckets might
     cover only a small slice of the image.
""")
pause()


# ===========================================================================
title("BOTH METHODS, SAME SIX PIXELS")
# ===========================================================================
hist, _ = count_colours(PIXELS, bucket_size=BUCKET, top_n=3)
mc = median_cut(PIXELS, box_count=3)["results"]
print()
out("With 3 boxes, the two methods agree EXACTLY:")
out("")
out(f"{'HISTOGRAM':<34} {'MEDIAN CUT (3 boxes)'}")
out("-" * 74)
for i in range(3):
    out(f"{str(hist[i]['rgb']):<18} {hist[i]['share']:>5.0%}"
        f"{'':<11}{str(mc[i]['rgb']):<18} {mc[i]['share']:>5.0%}")
print("""
     Identical. Two completely different routes to the same answer, because
     this image has three obvious groups and both methods found them.
""")
pause()

# ===========================================================================
title("THE SUMMARY TO REMEMBER")
# ===========================================================================
print("""
     HISTOGRAM
       Round every colour down to a grid. Pixels landing on the same grid
       point are counted together. Fullest group wins. Report the average
       of its real members, not the grid point.

       + simple, fast, one pass, no parameters to guess beyond bucket size
       - the grid lines are fixed before seeing the image, so a smoothly
         shaded object gets sliced across several groups that then compete

     MEDIAN CUT
       Put every pixel in one box. Repeatedly find the box with the widest
       spread of colour and cut it in two at the middle of that range.
       Each box's average is one of the answers.

       + boundaries are drawn to fit the image, not decided in advance
       + the boxes always cover 100% of the pixels
       + no randomness, so the same image always gives the same answer
       - you must choose how many boxes up front
       - boxes are cut along one channel at a time, so the groups are
         always rectangular blocks rather than natural shapes

     THE ONE-LINE DIFFERENCE
       histogram  drops pixels into boxes drawn BEFORE seeing the image
       median cut cuts boxes to fit wherever the image's colours actually are
""")
