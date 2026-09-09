import type { ColourResult } from "../types";

interface Props {
  palette: ColourResult[];
}

/**
 * The top N colours, as a proportional bar plus a ranked list.
 *
 * The bar uses each colour's share as its flex-grow, so the widths are the
 * actual proportions rather than an approximation. A minimum width keeps very
 * small slices visible instead of collapsing them to nothing.
 */
export default function Palette({ palette }: Props) {
  const total = palette.reduce((sum, colour) => sum + colour.share, 0);

  return (
    <div className="panel">
      <h2>Palette &middot; top {palette.length}</h2>

      <div
        className="palette-bar"
        role="img"
        aria-label={`Proportional palette: ${palette
          .map((c) => `${c.name} ${c.percentage}%`)
          .join(", ")}`}
      >
        {palette.map((colour, index) => (
          <div
            key={`${colour.hex}-${index}`}
            style={{ backgroundColor: colour.hex, flexGrow: colour.share }}
            title={`${colour.hex} — ${colour.percentage}%`}
          />
        ))}
      </div>

      <div>
        {palette.map((colour, index) => (
          <div className="palette-row" key={`${colour.hex}-${index}`}>
            <span className="palette-rank">{index + 1}</span>
            <span className="palette-swatch" style={{ backgroundColor: colour.hex }} />
            <span className="palette-hex">{colour.hex}</span>
            <span className="palette-name">{colour.name}</span>
            <span className="palette-share">{colour.percentage.toFixed(2)}%</span>
          </div>
        ))}
      </div>

      <p className="panel-note">
        {palette.length === 1
          ? `This colour accounts for ${(total * 100).toFixed(1)}% of the pixels counted.`
          : `These ${palette.length} colours account for ${(total * 100).toFixed(
              1,
            )}% of the pixels counted.`}
      </p>
    </div>
  );
}
