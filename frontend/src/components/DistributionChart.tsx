interface Bin {
  label: string;
  count: number;
  share: number;
  hex: string;
}

interface Props {
  title: string;
  bins: Bin[];
  emptyMessage: string;
  note?: string;
  /**
   * Label only every Nth bar. Twelve hue labels do not fit across a narrow
   * column -- they all truncate to ellipses, which reads as broken rather than
   * dense. Labelling alternate bars keeps the axis legible; the unlabelled bars
   * are still identified by their colour and their tooltip.
   */
  labelEvery?: number;
}

/**
 * A small bar chart, drawn with plain CSS rather than a charting library.
 *
 * Two simple bar charts do not justify the weight of a charting dependency, and
 * hand-rolling means each bar can be painted in the colour it represents --
 * which is the whole point here.
 *
 * Bars are scaled against the largest bin rather than the total. Scaling to the
 * total makes every bar unreadably short whenever one colour dominates, which
 * for this application is the common case rather than the exception.
 */
export default function DistributionChart({
  title,
  bins,
  emptyMessage,
  note,
  labelEvery = 1,
}: Props) {
  const peak = Math.max(...bins.map((bin) => bin.count), 0);

  return (
    <div>
      <h2
        style={{
          margin: "0 0 12px",
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: "0.09em",
          textTransform: "uppercase",
          color: "var(--text-faint)",
        }}
      >
        {title}
      </h2>

      {peak === 0 ? (
        <div className="chart-empty">{emptyMessage}</div>
      ) : (
        <div className="chart">
          {bins.map((bin, index) => (
            <div
              className="chart-column"
              key={bin.label}
              title={`${bin.label}: ${bin.count.toLocaleString()} pixels (${(
                bin.share * 100
              ).toFixed(1)}%)`}
            >
              <div
                className="chart-bar"
                style={{
                  height: `${Math.max((bin.count / peak) * 100, 1.5)}%`,
                  backgroundColor: bin.hex,
                }}
              />
              {/* A non-breaking space on skipped bars keeps every column the
                  same height, so the bars stay aligned along a common baseline. */}
              <span className="chart-label">
                {index % labelEvery === 0 ? bin.label : "\u00A0"}
              </span>
            </div>
          ))}
        </div>
      )}

      {note && <p className="panel-note">{note}</p>}
    </div>
  );
}
