import { useEffect, useMemo, useRef, useState } from "react";

import type { ExplainResponse, RGB } from "../types";

interface Props {
  data: ExplainResponse;
}

/**
 * Animated walkthrough of the counting algorithm.
 *
 * Every dot on screen is a real pixel sampled from the image being analysed, and
 * for median cut every box colour is one the algorithm genuinely produced. The
 * backend returns its own intermediate state (see `app/explain.py`) rather than
 * this component re-deriving it, so the animation cannot show one thing while
 * the analyser does another.
 *
 * Rendering is on a canvas rather than in SVG or the DOM: several hundred dots
 * moving and recolouring at once is exactly the case where per-element style
 * updates start dropping frames.
 *
 * The animation model is deliberately simple. Each stage is a pure function from
 * (stage, canvas size) to a layout; the renderer interpolates between the
 * previous stage's layout and the current one. Nothing is stored mid-transition,
 * so resizing the window or jumping between stages cannot leave it inconsistent.
 */

/** How long a transition takes, and how long it rests before auto-advancing. */
const TWEEN_MS = 900;
const HOLD_MS = 1100;

const DOT_RADIUS = 3.4;
const PADDING = 18;
const LABEL_BAND = 30;

type StageKind =
  | "image"
  | "quantise"
  | "count"
  | "rank"
  | "refine"
  | "scatter"
  | "cut"
  | "finished";

interface Stage {
  kind: StageKind;
  title: string;
  caption: string;
  /** Index into `data.iterations`, for the median-cut steps. */
  iteration?: number;
}

interface Dot {
  x: number;
  y: number;
  rgb: RGB;
  alpha: number;
  size: number;
}

interface Marker {
  x: number;
  y: number;
  rgb: RGB;
  rank: number;
  alpha: number;
}

interface Caption {
  x: number;
  y: number;
  text: string;
  colour: string;
  align: CanvasTextAlign;
  size: number;
  mono: boolean;
}

interface Layout {
  dots: Dot[];
  markers: Marker[];
  captions: Caption[];
}

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** Smooth acceleration and deceleration, so movement reads as deliberate. */
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

const mixRgb = (a: RGB, b: RGB, t: number): RGB => [
  lerp(a[0], b[0], t),
  lerp(a[1], b[1], t),
  lerp(a[2], b[2], t),
];

const css = (rgb: RGB, alpha = 1) =>
  `rgba(${Math.round(rgb[0])}, ${Math.round(rgb[1])}, ${Math.round(rgb[2])}, ${alpha})`;

function buildStages(data: ExplainResponse): Stage[] {
  const pixels = data.sampleSize.toLocaleString();
  const total = data.totalPixels.toLocaleString();

  if (data.method === "mediancut") {
    const stages: Stage[] = [
      {
        kind: "image",
        title: "Start with the pixels",
        caption: `${pixels} pixels sampled from the image, shown where they sit in it. The full run counts all ${total}.`,
      },
      {
        kind: "scatter",
        title: "Plot them in colour space",
        caption:
          "Each pixel becomes a point positioned by its colour, so similar colours sit near each other. This is a flat view of a 3D space, drawn against whichever two channels vary most in this image.",
      },
    ];

    data.iterations.forEach((iteration, index) => {
      stages.push(
        iteration.isFirst
          ? {
              kind: "cut",
              iteration: index,
              title: "Put everything in one box",
              caption:
                "Every pixel starts in a single box. Its colour is the average of the whole image, which is why it looks muddy — that is what we are about to fix.",
            }
          : {
              kind: "cut",
              iteration: index,
              title: `Cut ${iteration.step}`,
              caption: `Find whichever box has the widest spread of colour, and cut it in two at the middle of that range. ${
                iteration.boxes.length
              } boxes now. No randomness and nothing repeats until it settles — each cut is decided by the colours themselves.`,
            },
      );
    });

    stages.push({
      kind: "finished",
      title: "The fullest box wins",
      caption: `Every pixel is in exactly one box, so the boxes account for the whole image between them. The fullest one is the dominant colour: ${data.dominant.hex}, ${data.dominant.percentage}% of the image.`,
    });
    return stages;
  }

  return [
    {
      kind: "image",
      title: "Start with the pixels",
      caption: `${pixels} pixels sampled from the image, shown where they sit in it. The full run counts all ${total}.`,
    },
    {
      kind: "quantise",
      title: `Round every channel to a multiple of ${data.bucketSize}`,
      caption: `The image holds ${data.uniqueRawColours.toLocaleString()} exact colours. Rounding collapses near-identical shades onto the same value so they pool their votes instead of splitting them.`,
    },
    {
      kind: "count",
      title: "Drop each pixel into its bucket",
      caption: `Counting is a hash map: the bucket is the key, the tally is the value. One pass over the pixels, ${data.distinctColours.toLocaleString()} buckets occupied.`,
    },
    {
      kind: "rank",
      title: "The fullest bucket wins",
      caption: `${data.buckets[0]?.bucketHex ?? ""} holds more pixels than any other bucket, so that is the dominant colour.`,
    },
    {
      kind: "refine",
      title: "Report the true average, not the bucket label",
      caption:
        "The bucket label is a corner of a grid cell and may be a shade found nowhere in the image. Averaging the pixels that actually landed in it gives a colour genuinely present.",
    },
  ];
}

export default function AlgorithmAnimation({ data }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [stageIndex, setStageIndex] = useState(0);
  const [playing, setPlaying] = useState(true);

  const stages = useMemo(() => buildStages(data), [data]);

  // Where each pixel sits inside its bucket's column. Computed once so the
  // stacking does not reshuffle between frames.
  const slotInBucket = useMemo(() => {
    const seen = new Map<number, number>();
    return data.pixels.map((pixel) => {
      const next = seen.get(pixel.bucket) ?? 0;
      seen.set(pixel.bucket, next + 1);
      return next;
    });
  }, [data]);

  const hasOverflow = useMemo(() => data.pixels.some((p) => p.bucket < 0), [data]);

  // Progress through the current transition lives in a ref: it changes every
  // frame, and putting it in state would re-render the component 60 times a
  // second to draw something React does not manage.
  const progress = useRef({ stage: 0, startedAt: 0 });

  const reduceMotion = useMemo(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  // Restart whenever the underlying run changes, so the animation always
  // matches the image and settings currently on screen.
  useEffect(() => {
    setStageIndex(0);
    setPlaying(true);
    progress.current = { stage: 0, startedAt: 0 };
  }, [data]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    let frame = 0;
    let disposed = false;

    function draw(now: number) {
      if (disposed) return;
      const element = canvasRef.current;
      if (!element || !context) return;

      // Match the backing store to the display size and pixel density, or the
      // canvas renders blurry on a retina screen.
      const ratio = window.devicePixelRatio || 1;
      const displayWidth = element.clientWidth;
      const displayHeight = element.clientHeight;
      if (
        element.width !== Math.round(displayWidth * ratio) ||
        element.height !== Math.round(displayHeight * ratio)
      ) {
        element.width = Math.round(displayWidth * ratio);
        element.height = Math.round(displayHeight * ratio);
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, displayWidth, displayHeight);

      const rect: Rect = {
        x: PADDING,
        y: PADDING,
        width: displayWidth - PADDING * 2,
        height: displayHeight - PADDING * 2,
      };

      if (progress.current.stage !== stageIndex) {
        progress.current = { stage: stageIndex, startedAt: now };
      }
      if (progress.current.startedAt === 0) progress.current.startedAt = now;

      const elapsed = now - progress.current.startedAt;
      const raw = reduceMotion ? 1 : Math.min(elapsed / TWEEN_MS, 1);
      const t = ease(raw);

      const from = computeLayout(Math.max(stageIndex - 1, 0), rect);
      const to = computeLayout(stageIndex, rect);
      render(context, from, to, stageIndex === 0 ? 1 : t);

      frame = requestAnimationFrame(draw);
    }

    function computeLayout(index: number, rect: Rect): Layout {
      const stage = stages[index];
      if (!stage) return { dots: [], markers: [], captions: [] };
      return layoutFor(stage, rect, data, slotInBucket, hasOverflow);
    }

    function restartTween() {
      if (!document.hidden) progress.current.startedAt = 0;
    }

    document.addEventListener("visibilitychange", restartTween);
    frame = requestAnimationFrame(draw);
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", restartTween);
    };
  }, [data, stages, stageIndex, slotInBucket, hasOverflow, reduceMotion]);

  // Auto-advance while playing, stopping on the final stage.
  //
  // The timer is paused while the tab is hidden. Timers keep firing in a
  // background tab but requestAnimationFrame does not, so without this the
  // stages would march on invisibly and the viewer would return to find the
  // walkthrough several steps further along than they left it.
  useEffect(() => {
    if (!playing) return;
    if (stageIndex >= stages.length - 1) {
      setPlaying(false);
      return;
    }

    let timer = 0;
    const advance = () =>
      setStageIndex((current) => Math.min(current + 1, stages.length - 1));
    const schedule = () => {
      timer = window.setTimeout(advance, (reduceMotion ? 0 : TWEEN_MS) + HOLD_MS);
    };
    const onVisibilityChange = () => {
      window.clearTimeout(timer);
      if (!document.hidden) schedule();
    };

    if (!document.hidden) schedule();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [playing, stageIndex, stages.length, reduceMotion]);

  const stage = stages[stageIndex];
  const atEnd = stageIndex >= stages.length - 1;

  return (
    <div className="panel">
      <h2>How the algorithm works</h2>

      <canvas ref={canvasRef} className="algorithm-canvas" />

      <div className="algorithm-caption">
        <div className="algorithm-step">
          Step {stageIndex + 1} of {stages.length}
        </div>
        <h3>{stage?.title}</h3>
        <p>{stage?.caption}</p>
      </div>

      <div className="algorithm-controls">
        <button
          type="button"
          onClick={() => {
            if (atEnd) {
              setStageIndex(0);
              setPlaying(true);
            } else {
              setPlaying((current) => !current);
            }
          }}
          className="primary"
        >
          {atEnd ? "Replay" : playing ? "Pause" : "Play"}
        </button>
        <button
          type="button"
          onClick={() => {
            setPlaying(false);
            setStageIndex((current) => Math.max(current - 1, 0));
          }}
          disabled={stageIndex === 0}
        >
          Back
        </button>
        <button
          type="button"
          onClick={() => {
            setPlaying(false);
            setStageIndex((current) => Math.min(current + 1, stages.length - 1));
          }}
          disabled={atEnd}
        >
          Next
        </button>

        <div className="algorithm-dots" role="tablist" aria-label="Animation steps">
          {stages.map((entry, index) => (
            <button
              key={`${entry.kind}-${index}`}
              type="button"
              role="tab"
              aria-selected={index === stageIndex}
              aria-label={entry.title}
              className={index === stageIndex ? "active" : ""}
              onClick={() => {
                setPlaying(false);
                setStageIndex(index);
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- rendering -- */

function render(
  context: CanvasRenderingContext2D,
  from: Layout,
  to: Layout,
  t: number,
) {
  // Dots are matched by index across layouts -- particle N is always the same
  // sampled pixel -- so interpolating them pairwise is meaningful.
  const count = Math.max(from.dots.length, to.dots.length);
  for (let index = 0; index < count; index += 1) {
    const start = from.dots[index] ?? to.dots[index];
    const end = to.dots[index] ?? from.dots[index];
    if (!start || !end) continue;

    const alpha = lerp(start.alpha, end.alpha, t);
    if (alpha <= 0.01) continue;

    context.beginPath();
    context.arc(
      lerp(start.x, end.x, t),
      lerp(start.y, end.y, t),
      lerp(start.size, end.size, t),
      0,
      Math.PI * 2,
    );
    context.fillStyle = css(mixRgb(start.rgb, end.rgb, t), alpha);
    context.fill();
  }

  // Boxes are matched by rank rather than index, because a box's position in
  // the array is arbitrary while its rank (biggest first) is stable. That keeps
  // the animation's colours consistent with the palette shown beside it.
  const ranks = new Set([
    ...from.markers.map((marker) => marker.rank),
    ...to.markers.map((marker) => marker.rank),
  ]);
  for (const rank of ranks) {
    const start = from.markers.find((marker) => marker.rank === rank);
    const end = to.markers.find((marker) => marker.rank === rank);
    const a = start ?? end;
    const b = end ?? start;
    if (!a || !b) continue;

    const alpha = lerp(start ? a.alpha : 0, end ? b.alpha : 0, t);
    if (alpha <= 0.01) continue;

    const x = lerp(a.x, b.x, t);
    const y = lerp(a.y, b.y, t);
    const rgb = mixRgb(a.rgb, b.rgb, t);

    // The fill is semi-transparent so the box's own pixels stay visible
    // underneath it. A solid disc hides exactly the data the marker is there to
    // describe -- most obviously on an image of a few flat colours, where every
    // pixel in a box lands on the same point and vanishes beneath it.
    context.beginPath();
    context.arc(x, y, 11, 0, Math.PI * 2);
    context.fillStyle = css(rgb, 0.55 * alpha);
    context.fill();
    context.lineWidth = 2.5;
    context.strokeStyle = `rgba(255, 255, 255, ${0.85 * alpha})`;
    context.stroke();
  }

  // Text is not interpolated -- a cross-fade is far more legible than watching
  // one string morph into another.
  for (const caption of to.captions) {
    context.globalAlpha = t;
    context.fillStyle = caption.colour;
    context.textAlign = caption.align;
    context.font = `${caption.mono ? "500 " : "600 "}${caption.size}px ${
      caption.mono
        ? "ui-monospace, SFMono-Regular, Menlo, monospace"
        : "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    }`;
    context.fillText(caption.text, caption.x, caption.y);
    context.globalAlpha = 1;
  }
}

/* ------------------------------------------------------------------ layouts -- */

const MUTED = "rgba(154, 167, 182, 0.9)";
const FAINT = "rgba(107, 120, 136, 0.9)";
const BRIGHT = "rgba(230, 237, 243, 0.95)";

function layoutFor(
  stage: Stage,
  rect: Rect,
  data: ExplainResponse,
  slotInBucket: number[],
  hasOverflow: boolean,
): Layout {
  switch (stage.kind) {
    case "image":
      return imageLayout(rect, data, false);
    case "quantise":
      return imageLayout(rect, data, true);
    case "count":
      return bucketLayout(rect, data, slotInBucket, hasOverflow, null);
    case "rank":
      return bucketLayout(rect, data, slotInBucket, hasOverflow, 0);
    case "refine":
      return bucketLayout(rect, data, slotInBucket, hasOverflow, 0, true);
    case "scatter":
      return scatterLayout(rect, data, null);
    case "cut":
      return scatterLayout(rect, data, stage.iteration ?? 0);
    case "finished":
      return scatterLayout(rect, data, data.iterations.length - 1, true);
    default:
      return { dots: [], markers: [], captions: [] };
  }
}

/** Pixels arranged as they appear in the source image. */
function imageLayout(rect: Rect, data: ExplainResponse, quantised: boolean): Layout {
  const aspect =
    data.image.sampledHeight > 0
      ? data.image.sampledWidth / data.image.sampledHeight
      : 1;

  const available = { width: rect.width, height: rect.height - LABEL_BAND };
  let width = Math.min(available.width * 0.72, available.height * aspect);
  let height = width / aspect;
  if (height > available.height) {
    height = available.height;
    width = height * aspect;
  }

  const left = rect.x + (rect.width - width) / 2;
  const top = rect.y + (available.height - height) / 2;

  const dots: Dot[] = data.pixels.map((pixel) => ({
    x: left + pixel.imagePosition[0] * width,
    y: top + pixel.imagePosition[1] * height,
    rgb: quantised && pixel.quantisedRgb ? pixel.quantisedRgb : pixel.rgb,
    alpha: 1,
    size: DOT_RADIUS,
  }));

  const captions: Caption[] = [];
  const example = data.pixels[0];
  if (quantised && example?.quantisedRgb) {
    // One worked example makes the operation concrete in a way the prose above
    // the canvas cannot.
    captions.push({
      x: rect.x + rect.width / 2,
      y: rect.y + rect.height - 6,
      text: `${example.rgb.join(", ")}  →  ${example.quantisedRgb.join(", ")}`,
      colour: BRIGHT,
      align: "center",
      size: 13,
      mono: true,
    });
  } else {
    captions.push({
      x: rect.x + rect.width / 2,
      y: rect.y + rect.height - 6,
      text: `${data.sampleSize} sampled pixels`,
      colour: FAINT,
      align: "center",
      size: 12,
      mono: false,
    });
  }

  return { dots, markers: [], captions };
}

/** Pixels stacked into one column per bucket, tallest wins. */
function bucketLayout(
  rect: Rect,
  data: ExplainResponse,
  slotInBucket: number[],
  hasOverflow: boolean,
  highlight: number | null,
  showRefinement = false,
): Layout {
  const columnCount = data.buckets.length + (hasOverflow ? 1 : 0);
  const columnWidth = rect.width / Math.max(columnCount, 1);
  const floor = rect.y + rect.height - LABEL_BAND;

  const step = DOT_RADIUS * 2 + 1.6;

  // Choose the narrowest column that still fits the biggest bucket in the
  // available height. Filling the column width instead would spread each bucket
  // into a wide slab, where the relative sizes read as area -- which the eye
  // compares poorly. Narrow stacks turn the same data into bar heights, which
  // is the comparison the chart is actually asking the viewer to make.
  const widest = Math.max(1, Math.floor((columnWidth - 12) / step));
  const rowsAvailable = Math.max(1, Math.floor((rect.height - LABEL_BAND - 24) / step));
  const largestBucket = data.pixels.reduce((most, pixel) => {
    if (pixel.bucket !== 0) return most;
    return most + 1;
  }, 0);
  const perRow = Math.min(
    widest,
    Math.max(1, Math.ceil(Math.max(largestBucket, 1) / rowsAvailable)),
  );

  const dots: Dot[] = data.pixels.map((pixel, index) => {
    // Pixels outside the top N gather in a trailing column, dimmed. Hiding them
    // would quietly misrepresent how much of the image the buckets cover.
    const column = pixel.bucket >= 0 ? pixel.bucket : data.buckets.length;
    const slot = slotInBucket[index] ?? 0;
    const row = Math.floor(slot / perRow);
    const positionInRow = slot % perRow;

    const columnLeft = rect.x + column * columnWidth;
    const inset = (columnWidth - perRow * step) / 2;

    const dimmed = highlight !== null && pixel.bucket !== highlight;
    const outside = pixel.bucket < 0;

    return {
      x: columnLeft + inset + positionInRow * step + step / 2,
      y: floor - 6 - row * step - step / 2,
      rgb: pixel.quantisedRgb ?? pixel.rgb,
      alpha: outside ? 0.22 : dimmed ? 0.3 : 1,
      size: DOT_RADIUS,
    };
  });

  const captions: Caption[] = [];
  data.buckets.forEach((bucket, index) => {
    const centre = rect.x + index * columnWidth + columnWidth / 2;
    const dim = highlight !== null && index !== highlight;
    captions.push({
      x: centre,
      y: floor + 15,
      text: `${bucket.percentage.toFixed(1)}%`,
      colour: dim ? FAINT : BRIGHT,
      align: "center",
      size: 12,
      mono: true,
    });
    captions.push({
      x: centre,
      y: floor + 28,
      text: showRefinement && index === highlight ? bucket.hex : bucket.bucketHex,
      colour: dim ? "rgba(107, 120, 136, 0.6)" : MUTED,
      align: "center",
      size: 10,
      mono: true,
    });
  });

  if (hasOverflow) {
    captions.push({
      x: rect.x + data.buckets.length * columnWidth + columnWidth / 2,
      y: floor + 15,
      text: "other",
      colour: FAINT,
      align: "center",
      size: 11,
      mono: false,
    });
  }

  const winner = highlight !== null ? data.buckets[highlight] : undefined;
  if (showRefinement && winner) {
    captions.push({
      x: rect.x + rect.width / 2,
      y: rect.y + 14,
      text: `bucket ${winner.bucketHex}  →  true average ${winner.hex}`,
      colour: BRIGHT,
      align: "center",
      size: 13,
      mono: true,
    });
  }

  return { dots, markers: [], captions };
}

/** Pixels positioned by colour, with each box's average drawn among them. */
function scatterLayout(
  rect: Rect,
  data: ExplainResponse,
  iterationIndex: number | null,
  finished = false,
): Layout {
  // The plot uses the full rectangle rather than a centred square. The backend
  // already scales the two projected axes independently (see `_normalise` in
  // app/explain.py), so the picture is not metric in either case -- and a square
  // plot inside a wide canvas throws away most of the width, squeezing the
  // boxes into a narrow band where nothing can be made out.
  const plotWidth = rect.width;
  const plotHeight = rect.height - LABEL_BAND;
  const left = rect.x;
  const top = rect.y;

  const iteration =
    iterationIndex === null ? null : data.iterations[iterationIndex] ?? null;

  const dots: Dot[] = data.pixels.map((pixel, index) => {
    const position = pixel.colourPosition ?? [0.5, 0.5];
    const boxIndex = iteration?.assignments[index];
    const box =
      boxIndex !== undefined ? iteration?.boxes[boxIndex] : undefined;

    return {
      x: left + position[0] * plotWidth,
      y: top + (1 - position[1]) * plotHeight,
      // Once the boxes exist, each pixel takes its box's colour. That recolour
      // *is* what "this pixel is in that box" looks like.
      rgb: box ? box.rgb : pixel.rgb,
      alpha: box ? 0.75 : 0.9,
      size: DOT_RADIUS,
    };
  });

  const markers: Marker[] = (iteration?.boxes ?? []).map((box) => ({
    x: left + box.position[0] * plotWidth,
    y: top + (1 - box.position[1]) * plotHeight,
    rgb: box.rgb,
    rank: box.rank,
    alpha: 1,
  }));

  const captions: Caption[] = [
    {
      x: rect.x + rect.width / 2,
      y: rect.y + rect.height - 6,
      text: finished
        ? `fullest box ${data.dominant.hex} · ${data.dominant.percentage}%`
        : iteration
          ? `${iteration.boxes.length} boxes · ${iteration.boxes
              .map((box) => `${Math.round(box.share * 100)}%`)
              .join(" · ")}`
          : "each dot is one pixel, positioned by its colour",
      colour: finished ? BRIGHT : FAINT,
      align: "center",
      size: 12,
      mono: finished || Boolean(iteration),
    },
  ];

  return { dots, markers, captions };
}
