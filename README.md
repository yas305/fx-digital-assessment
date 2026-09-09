# Dominant Colour Finder

Finds the most frequently occurring colour in an image.

A Python backend does the analysis and exposes it over a REST API; a TypeScript
frontend presents the result with supporting statistics and an animated
walkthrough of the algorithm. The same analysis also runs as a command-line
program.

- **Challenge One** — load an image, reduce the colour space, count, report the
  dominant RGB value.
- **Challenge Two** — all three optional features: dictionary-based counting,
  colour exclusion, and top-N results.

---

## Running it

Two processes. Both need to be running for the web interface.

**Backend** — first time only, from `backend/`:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

Then, every time:

```bash
python main.py
```

**Frontend** — first time only, from `frontend/`:

```bash
npm install
```

Then, every time:

```bash
npm run dev
```

`main.py` starts the API on port 8000 with auto-reload. If you run it with a
Python that does not have the dependencies, it finds the virtual environment in
`backend/` and re-runs itself with that — so forgetting to activate the venv is
not a problem. `--port` and `--no-reload` are available if you need them.

Then open <http://localhost:5173>. Interactive API documentation is generated
automatically at <http://localhost:8000/docs>.

Six demo images are bundled, so there is something to analyse without finding a
photograph first.

### Command line

The analysis also runs standalone, with no server involved (from `backend/`):

```bash
./.venv/bin/python cli.py path/to/image.jpg
```

```bash
./.venv/bin/python cli.py photo.jpg --top 5 --method kmeans
```

```bash
./.venv/bin/python cli.py product.jpg --ignore-white --json
```

`--help` lists every option. In a colour-capable terminal it prints real
swatches beside the values.

### Tests

```bash
cd backend && ./.venv/bin/python -m pytest
```

70 tests covering the counting logic, both methods, the filters, image loading
edge cases, end-to-end analysis, the animation data and the HTTP routes.

---

## The approach

### The problem underneath

Finding a dominant colour is a counting problem. An image is a grid of pixels,
each pixel is an `(R, G, B)` triple, and the question is which triple occurs
most often. The image handling is just the loading step.

The complication is that counting raw colours gives a near-useless answer. There
are 256³ = 16.7 million possible colours. A photograph of a blue sky contains
thousands of *slightly* different blues — which a person calls one colour and a
computer calls thousands, each with a tally of about one. Meanwhile any small
patch of perfectly flat colour wins by default.

The `noisy-sky` demo image is exactly this: thousands of near-identical blues
against one flat white block covering 7% of the image. Counted raw, the white
block wins.

### Method one — round, then count

Round each channel down to a multiple of the bucket size, so near-identical
shades land on the same value and pool their votes. Then count with a
dictionary: the rounded colour is the key, the tally is the value. One pass.

Two details worth pointing out:

**Rounding down, not to nearest.** Rounding to the nearest multiple makes the
first and last buckets half-width, which quietly biases results toward pure
black and pure white — the two colours most likely to be a background nobody
cares about.

**The reported colour is the bucket's true average, not its label.** A bucket
label is a corner of a grid cell and may be a shade appearing nowhere in the
image. A second dictionary keeps a running sum of the *original* colours in each
bucket, so the winner is reported as the average of its real members — a colour
genuinely present.

**The known weakness** is that the grid boundaries are arbitrary. Two shades that
look identical can straddle a boundary and split their votes.
`test_bucket_boundaries_can_split_a_colour` documents it: blue values 200–209
split 80/20 at a bucket size of 16, because the grid line falls at 208. This is
why the second method exists.

### Method two — k-means clustering

Picture ice-cream vans parking in a town. Park k vans, every resident walks to
their nearest one, each van moves to the middle of its own customers, and some
residents now find a different van is nearer — so repeat. Eventually nothing
moves. The town is colour space, the residents are pixels, the vans are cluster
centres, and the busiest van is the dominant colour.

The difference from the histogram is **where the boundaries fall**. The histogram
draws them on a fixed grid decided before anyone looked at the image, so a
smoothly shaded object gets sliced into pieces that then compete against each
other. k-means puts its boundaries wherever colours are sparse, so a shaded
object stays in one group.

Three choices in it are deliberate:

- **k-means++ seeding.** Dropping centres at random risks two landing in the same
  neighbourhood, squabbling over one group while another part of the image is
  ignored. Each centre after the first is chosen with a preference for colours
  far from those already placed.
- **A fixed random seed.** Textbook k-means returns a slightly different answer
  every run, which is no use in an API — run it twice, get two answers, look
  broken.
- **Rounding to multiples of 8 before clustering.** A 400px photograph holds
  around 115,000 distinct colours, and clustering that many points in plain
  Python takes minutes; rounding first cuts it to about 6,600. Crucially the
  rounding decides only what gets *grouped*, never what gets *reported* — each
  group is represented by the average of its real colours, so an image of exactly
  `(34, 148, 148)` still returns exactly that.

### Comparing the two

They answer different questions, and on a colourful photograph they disagree
sharply:

| | Histogram | k-means |
|---|---|---|
| The question | "Which single shade appears most often?" | "If I had to describe this image with k colours, which k?" |
| Boundaries | A fixed grid | Found from the data |
| You must choose | bucket size | k |
| Coverage | The top 6 might be 5% of the image | The k clusters always cover 100% |
| Speed | One pass | Repeats until settled |

That coverage row is the important one. On a photograph of forty macarons the
histogram reports a dominant colour worth **1.2%**, because the yellow macarons
alone are sliced by shading into dozens of adjacent buckets that each compete
separately. k-means merges them and reports that same yellow at **22%**. Neither
is wrong; the histogram is answering a question that photograph does not have a
good answer to.

On the `blocks` demo image — flat colours, no shading — both give identical
answers, because there is no ramp for the grid to slice.

### Seeing it run

The **How it works** tab animates the algorithm over whatever image is loaded.

It is not an illustration drawn to resemble the algorithm. The backend returns
its genuine intermediate state — a sample of several hundred real pixels, and
either their bucket assignments or the complete history of the k-means centres —
and the frontend replays it. `test_explanation_agrees_with_the_analysis` asserts
the two cannot disagree.

Some detail worth knowing:

- **It draws to a canvas, not the DOM.** Several hundred dots moving and
  recolouring at once is where per-element style updates start dropping frames.
- **Each stage is a pure function from (stage, canvas size) to a layout**, and the
  renderer interpolates between consecutive layouts. Nothing is stored
  mid-transition, so resizing or skipping between steps cannot leave it
  inconsistent.
- **Centres are matched between frames by rank, not array index.** A centre's
  index is arbitrary; its rank is stable. That is what makes a centre appear to
  *move* between iterations rather than teleport.
- **Auto-advance pauses when the tab is hidden.** Timers keep firing in a
  background tab but `requestAnimationFrame` does not, so without this the steps
  would march on invisibly.

### Colour exclusion

Challenge Two's "ignore certain colours". Rather than hardcoding white and black,
the rules are written in **HSV**, which separates *which* colour something is
(hue) from *how vivid* (saturation) and *how bright* (value). That makes "ignore
greys" a single saturation threshold instead of an endless blocklist.

The `product-on-white` demo is the motivating case: a crimson product on a white
backdrop. The literal dominant colour is the backdrop at 76%, which is never what
anyone wants. Excluding near-white (value above 0.85, so off-whites and paper
textures are caught too) surfaces the product.

---

## Decisions worth explaining

**No NumPy, and almost no classes.** The biggest decisions in the project, both
made deliberately.

*No NumPy* — measured before deciding.

A vectorised NumPy implementation ran the counting in about 16ms against 134ms
for the plain version — roughly 7× faster. But at these image sizes both are
instant to a person, and the NumPy version hid the idea behind machinery
(`np.unique(..., return_inverse=True)`, `bincount`, `lexsort`, packing three
channels into one integer) that takes longer to explain than the algorithm it
implements. The brief asks for well-documented code and suggests a dictionary for
counting; plain Python *is* the expected solution.

The full pipeline on a 400×400 photograph with 115,000 distinct colours:

| | Time |
|---|---|
| Histogram, top 6 | ~190 ms |
| k-means, k = 6 | ~300 ms |

Pillow remains, because decoding a JPEG is not something to write by hand. It is
used only to turn a file into a list of pixels; every calculation after that is
standard library. Two files — `colour.py` and `cli.py` — import nothing outside
it at all.

*Almost no classes.* There are exactly two in the project, and both are
exception types (`ImageLoadError`, `AnalysisError`), because you cannot raise
something that is not a class. Everything else is plain functions operating on
plain data: a colour is a `(red, green, blue)` tuple, an image is a list of them,
and every result is a dictionary.

That means there is no indirection between reading the code and knowing what it
does. To see what the API returns, read the dictionary in `analyse()` — the JSON
keys are written out literally, so what you see is what the browser receives.

The cost is real and worth stating: dictionaries give up editor autocomplete and
type checking, so a typo like `result["dominat"]` fails at runtime rather than
being caught as you type. On a larger or longer-lived codebase that trade would
go the other way. Here, being able to read the whole thing top to bottom matters
more.

**Transparent pixels are discarded.** A PNG logo on a transparent background
still stores a colour underneath the see-through part — usually pure black.
Counting invisible pixels hands the win to a colour nobody can see. The
`transparent` demo is 86% transparent-black and correctly reports purple.

**Shrinking uses nearest-neighbour, not smooth resampling.** Dominant colour is a
statistical property, so a 12MP photo does not need every pixel inspected.
But the resampling filter matters: bilinear and Lanczos *blend* neighbouring
pixels, inventing colours never in the image — precisely the thing being
measured. Nearest-neighbour just picks existing pixels, making the shrink an
unbiased sample.

**Grey pixels are excluded from the hue chart.** A grey pixel has no meaningful
hue; the conversion returns 0, which is red. Including them files every grey
pixel under "Red" and produces a confidently wrong chart.

**Colour names use redmean, not straight RGB distance.** Plain RGB distance
disagrees with human vision — it over-weights blue and under-weights green — so
nearest-match naming produces names that feel wrong. Redmean is a cheap, known
correction that gets most of the benefit of a full perceptual colour space.

**Ties are broken explicitly.** Where two buckets hold the same number of pixels,
the winner is decided by colour rather than by whichever pixel happened to appear
first. Without that the same image could give different answers on different runs.

---

## Layout

```
backend/
  app/
    dominant.py   The algorithm: loading, filtering, counting, clustering, sampling
    colour.py     Colour conversions and naming
    samples.py    Demo images, drawn in code
    api.py        Response building and HTTP routes
  main.py         Starts the API:  python main.py
  cli.py          Standalone command-line entry point
  tests/          70 tests
frontend/
  src/
    App.tsx       State, debouncing, request cancellation
    lib/api.ts    Backend client
    types.ts      Mirrors of the API schemas
    components/   Uploader, Controls, DominantCard, Palette, charts, stats
      AlgorithmAnimation.tsx   Canvas walkthrough of the algorithm
```

Four Python modules, deliberately. `dominant.py` is the file to read — it is the
whole algorithm, start to finish, in ten functions, and it knows nothing about
HTTP or JSON. Delete `api.py` and the command line still works.

---

## Known limitations

- **The TypeScript types are hand-maintained.** FastAPI publishes an OpenAPI
  schema at `/openapi.json`; on a longer-lived project these would be generated
  from it so the two cannot drift apart.
- **Clustering happens in RGB space, not a perceptual one.** CIELAB is engineered
  so equal numeric distance matches equal perceived difference, which would make
  clusters align better with what a person would group. The HSV filtering already
  covers the most visible symptom.
- **`k` must be chosen in advance.** Mean-shift clustering finds the number of
  groups on its own, at a significant cost in speed.
- **The animation's colour-space scatter is not metric.** The two axes are scaled
  independently so the plot fills the canvas, which stretches the picture: it
  shows *which* points group together, not how far apart they truly are.
- **The frontend has no automated tests.** The analysis logic — the part with the
  interesting edge cases — is tested thoroughly on the Python side, and the
  TypeScript is typechecked in strict mode, but the React components and canvas
  layout functions are verified by hand.
- **Animated images analyse the first frame only**, which is the sensible reading
  of "the colour of this image" but is worth stating.
