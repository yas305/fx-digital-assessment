import type { AnalysisResponse } from "../types";

interface Props {
  result: AnalysisResponse;
}

function Stat({ label, figure, sub }: { label: string; figure: string; sub?: string }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="figure">{figure}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

/**
 * Numbers describing the run.
 *
 * The pairing worth noticing is "exact colours" against "after grouping": it
 * makes the effect of quantisation concrete. A photo might contain 40,000 exact
 * RGB values that collapse into 300 groups, which is precisely why counting raw
 * values gives such a poor answer.
 */
export default function StatsPanel({ result }: Props) {
  const { stats, image, filters, method } = result;

  return (
    <div className="panel">
      <h2>Analysis detail</h2>
      <div className="stat-grid">
        <Stat
          label="Exact colours"
          figure={stats.uniqueRawColours.toLocaleString()}
          sub="distinct RGB values"
        />
        <Stat
          label="After grouping"
          figure={stats.distinctColours.toLocaleString()}
          sub={method === "mediancut" ? "boxes made" : "occupied buckets"}
        />
        <Stat
          label="Pixels counted"
          figure={filters.pixelsCounted.toLocaleString()}
          sub={`of ${image.totalPixels.toLocaleString()} original`}
        />
        <Stat
          label="Colourfulness"
          figure={`${Math.round(stats.colourfulness * 100)}%`}
          sub={stats.colourfulness < 0.25 ? "close to monochrome" : "varied hues"}
        />
        <Stat
          label="Avg saturation"
          figure={`${Math.round(stats.averageSaturation * 100)}%`}
        />
        <Stat
          label="Avg brightness"
          figure={`${Math.round(stats.averageLightness * 100)}%`}
        />
        <Stat
          label="Source"
          figure={`${image.width}×${image.height}`}
          sub={
            image.wasDownsampled
              ? `sampled at ${image.sampledWidth}×${image.sampledHeight}`
              : `${image.format} · full resolution`
          }
        />
        <Stat
          label="Time taken"
          figure={`${stats.durationMs.toFixed(1)} ms`}
          sub={stats.iterations !== null ? `${stats.iterations} cuts made` : undefined}
        />
      </div>

      {(filters.active || image.transparentDropped > 0) && (
        <p className="panel-note">
          {filters.active && (
            <>
              Excluded {filters.totalRemoved.toLocaleString()} pixels
              {filters.removedTooLight > 0 &&
                ` · ${filters.removedTooLight.toLocaleString()} too light`}
              {filters.removedTooDark > 0 &&
                ` · ${filters.removedTooDark.toLocaleString()} too dark`}
              {filters.removedLowSaturation > 0 &&
                ` · ${filters.removedLowSaturation.toLocaleString()} washed out`}
              {filters.removedIgnored > 0 &&
                ` · ${filters.removedIgnored.toLocaleString()} explicitly ignored`}
              .{" "}
            </>
          )}
          {image.transparentDropped > 0 && (
            <>
              Discarded {image.transparentDropped.toLocaleString()} transparent pixels,
              which are invisible and must not count towards the result.
            </>
          )}
        </p>
      )}
    </div>
  );
}
