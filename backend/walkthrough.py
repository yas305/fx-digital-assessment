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
    cluster_colours,
    count_colours,
    distance_squared,
    nearest_centre,
    quantise_pixel,
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
title("K-MEANS, PART 1 -- what we have and what we must produce")
# ===========================================================================
print("""
     WE HAVE:  the same six pixels, and a number k.
""")
for i, p in enumerate(PIXELS, 1):
    out(f"pixel {i}: {p}")
print("""
     k = 2      we are asking for 2 groups

     WE MUST PRODUCE:  2 colours, and how many pixels each represents.

     Those 2 colours are called CENTRES. A centre is just a colour -- three
     numbers, exactly like a pixel. The difference is that a pixel comes
     from the image, and a centre is something we calculate.
""")
pause()


# ===========================================================================
title("K-MEANS, PART 2 -- where the first centres come from")
# ===========================================================================
print("""
     We cannot calculate a centre yet. Calculating one means averaging the
     pixels that belong to it, and nothing belongs to anything yet.

     So we start by PICKING two of the actual pixels to BE the first
     centres. Not inventing colours -- literally picking two out of the list.
     That is what pick_starting_centres() does.

     For this walkthrough we use:
""")
CENTRES_START = [(203, 12, 8), (15, 190, 20)]
out(f"centre A = {CENTRES_START[0]}      (this is pixel 1)")
out(f"centre B = {CENTRES_START[1]}     (this is pixel 6)")
print("""
     These are only a STARTING GUESS. They get replaced in Part 5.
""")
pause()


# ===========================================================================
title("K-MEANS, PART 3 -- the comparison: WHICH two colours, and why")
# ===========================================================================
print("""
     Now we decide, for EVERY pixel, whether it belongs to A or B. We
     measure how different the pixel is from A, and from B, and pick
     whichever is smaller.

     So distance_squared() is ALWAYS called with:

         argument 1 = the pixel we are currently looking at
         argument 2 = one of the centres

     It runs once per centre, for every pixel. Six pixels, two centres,
     so twelve calls in total.
""")
code("red   = first[0] - second[0]",
     "green = first[1] - second[1]",
     "blue  = first[2] - second[2]",
     "return red * red + green * green + blue * blue")
print()
out("Here are the first two calls, both for PIXEL 1:")
print()
p = PIXELS[0]
for name, centre in zip("AB", CENTRES_START):
    out(f"distance_squared({p}, {centre})      <- pixel 1 vs centre {name}")
    d = [p[i] - centre[i] for i in range(3)]
    out(f"    red    {p[0]:>3} - {centre[0]:<3} = {d[0]:>5}   squared = {d[0]**2:>7,}")
    out(f"    green  {p[1]:>3} - {centre[1]:<3} = {d[1]:>5}   squared = {d[1]**2:>7,}")
    out(f"    blue   {p[2]:>3} - {centre[2]:<3} = {d[2]:>5}   squared = {d[2]**2:>7,}")
    out(f"    added up                          = {distance_squared(p, centre):>7,}")
    print()
out(f"distance to A = {distance_squared(p, CENTRES_START[0]):>7,}")
out(f"distance to B = {distance_squared(p, CENTRES_START[1]):>7,}")
out(f"-> A is smaller, so pixel 1 belongs to centre A.")
print("""
     That comparison is all nearest_centre() does: run distance_squared
     once per centre, return the position of the smallest.
""")
pause()


# ===========================================================================
title("K-MEANS, PART 4 -- do that for all six pixels")
# ===========================================================================
centres = list(CENTRES_START)
print()
out(f"{'pixel':<18} {'vs A':>12} {'vs B':>12}   belongs to")
out("-" * 60)
groups = [[], []]
for p in PIXELS:
    da, db = distance_squared(p, centres[0]), distance_squared(p, centres[1])
    groups[nearest_centre(p, centres)].append(p)
    out(f"{str(p):<18} {da:>12,} {db:>12,}   {'A' if da <= db else 'B'}")
print()
out(f"group A = {groups[0]}")
out(f"group B = {groups[1]}")
print("""
     Every pixel now belongs to exactly one centre.
""")
pause()


# ===========================================================================
title("K-MEANS, PART 5 -- replace each centre with the average of its group")
# ===========================================================================
print("""
     The starting centres were a guess. Now we know which pixels chose
     each one, so we can calculate a better centre: the average of its
     group -- worked out one channel at a time, exactly like the histogram.
""")
new_centres = []
for name, group, old in zip("AB", groups, centres):
    print()
    out(f"CENTRE {name}   old value {old}")
    out(f"   group: {group}")
    out("")
    avg = []
    for ch, label in enumerate(("red  ", "green", "blue ")):
        vals = [q[ch] for q in group]
        s = sum(vals)
        avg.append(round(s / len(vals)))
        out(f"   {label}  {' + '.join(str(v) for v in vals)} = {s}"
            f"   ->  {s} / {len(vals)} = {s/len(vals):.2f}  ->  {round(s/len(vals))}")
    avg = tuple(avg)
    new_centres.append(avg)
    out("")
    out(f"   new value {avg}   -- it changed by "
        f"{distance_squared(old, avg) ** 0.5:.1f}")
print("""
     Look at centre B. Its old value was a GREEN, but its group holds two
     blues and one green. Their average is a blue-green. So B changed a
     lot -- the starting guess was bad, and the average corrects it.

     Nothing "slides". The old number is thrown away and a new one
     calculated. The change figure is only measured so we know when to stop.
""")
pause()


# ===========================================================================
title("K-MEANS, PART 6 -- decide whether to stop")
# ===========================================================================
furthest = max(distance_squared(o, n) ** 0.5 for o, n in zip(centres, new_centres))
code("if furthest_move < SETTLED:      # SETTLED = 0.5",
     "    break")
print()
out(f"largest change in Part 5 = {furthest:.1f}")
out(f"{furthest:.1f} is bigger than 0.5, so we do NOT stop.")
print("""
     Why go round again? The centres sit somewhere different now, so a
     pixel that was nearest to A before might be nearest to B now. If the
     groups change, the averages change, so the centres must be
     recalculated again.
""")
centres = new_centres
pause()


# ===========================================================================
title("K-MEANS, PART 7 -- round 2, exactly the same two steps")
# ===========================================================================
print()
out(f"centres are now:  A = {centres[0]}      B = {centres[1]}")
print()
out(f"{'pixel':<18} {'vs A':>12} {'vs B':>12}   belongs to")
out("-" * 60)
groups = [[], []]
for p in PIXELS:
    da, db = distance_squared(p, centres[0]), distance_squared(p, centres[1])
    groups[nearest_centre(p, centres)].append(p)
    out(f"{str(p):<18} {da:>12,} {db:>12,}   {'A' if da <= db else 'B'}")
print()
out(f"group A = {groups[0]}")
out(f"group B = {groups[1]}")
out("")
out("THE SAME GROUPS AS ROUND 1. Nobody switched.")
print()
final = []
for name, group, old in zip("AB", groups, centres):
    avg = tuple(round(sum(q[ch] for q in group) / len(group)) for ch in range(3))
    final.append(avg)
    out(f"centre {name}: average of the same group = {avg}   "
        f"(was {old}, changed by {distance_squared(old, avg) ** 0.5:.1f})")
furthest = max(distance_squared(o, n) ** 0.5 for o, n in zip(centres, final))
print()
out(f"largest change = {furthest:.1f}  ->  less than 0.5  ->  break. Finished.")
print("""
     That is what "converged" means: the same pixels chose the same
     centres, so the averages came out identical, so nothing changed.
     Going round again would produce the same result forever.
""")
centres = final
pause()


# ===========================================================================
title("K-MEANS, PART 8 -- the answer")
# ===========================================================================
counts = [0, 0]
for p in PIXELS:
    counts[nearest_centre(p, centres)] += 1
print()
for i in sorted(range(2), key=lambda x: -counts[x]):
    out(f"{str(centres[i]):<18} {counts[i]} of 6 pixels   {counts[i]/6:>4.0%}")
print("""
     The dominant colour is the centre holding the most pixels.
""")
pause()


# ===========================================================================
title("BOTH METHODS, SAME SIX PIXELS")
# ===========================================================================
hist, _ = count_colours(PIXELS, bucket_size=BUCKET, top_n=3)
km3 = cluster_colours(PIXELS, k=3)["results"]
print()
out("With k = 3, the two methods agree EXACTLY:")
out("")
out(f"{'HISTOGRAM':<34} {'K-MEANS (k=3)'}")
out("-" * 74)
for i in range(3):
    out(f"{str(hist[i]['rgb']):<18} {hist[i]['share']:>5.0%}"
        f"{'':<11}{str(km3[i]['rgb']):<18} {km3[i]['share']:>5.0%}")
print("""
     Identical. Two completely different routes to the same answer, because
     this image has three obvious groups and both methods found them.
""")
pause()

km2 = cluster_colours(PIXELS, k=2)["results"]
print()
out("Now the same thing with k = 2 -- and it goes wrong:")
out("")
for c in km2:
    out(f"{str(c['rgb']):<18} {c['count']} pixels  {c['share']:>5.0%}")
print(f"""
     Only two groups were allowed, so the lone green pixel had nowhere to
     go and joined the two blues. Their average is {km2[0]['rgb'] if km2[0]['rgb'][2] > 100 else km2[1]['rgb']} -- a
     blue-green that NO PIXEL IN THE IMAGE ACTUALLY IS.

     Worse, both groups now hold 3 pixels each: a 50/50 tie. The winner is
     decided by the tie-break rule (lowest colour value first), not by the
     image. So "the dominant colour" here is essentially arbitrary.

     THAT is the cost of choosing k badly, and it is the honest weakness of
     k-means: you must pick k before you know how many groups exist. The
     histogram found three groups without being told how many to look for.
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

     K-MEANS
       Drop k centres. Every pixel joins its nearest. Each centre is then
       recomputed as the average of whoever joined -- the position with the
       smallest total distance to them. Repeat until nothing moves.

       + boundaries land where the image's colours actually are
       + the k groups always cover 100% of the pixels
       - you must choose k in advance, and choosing badly invents a colour
         that is not in the image

     THE ONE-LINE DIFFERENCE
       histogram  drops pixels into boxes drawn BEFORE seeing the image
       k-means    moves centres to wherever the image's colours actually are
""")
