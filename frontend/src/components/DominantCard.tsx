import { useEffect, useState } from "react";

import type { ColourResult } from "../types";

interface Props {
  colour: ColourResult;
  pixelsCounted: number;
}

/**
 * The headline result: one large swatch and the numbers describing it.
 *
 * Text on the swatch is switched between black and white based on the colour's
 * measured luminance, so the label stays readable whatever colour lands here.
 */
export default function DominantCard({ colour, pixelsCounted }: Props) {
  const [copied, setCopied] = useState(false);

  // Reset the "Copied" state whenever the colour changes, so a stale
  // confirmation never sits under a different colour.
  useEffect(() => setCopied(false), [colour.hex]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(colour.hex);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Clipboard access can be denied (insecure origin, permissions policy).
      // The hex is on screen to copy by hand, so this is not worth an alert.
    }
  }

  const [r, g, b] = colour.rgb;

  return (
    <div className="panel">
      <h2>Dominant colour</h2>
      <div className="dominant">
        <div
          className="dominant-swatch"
          style={{
            backgroundColor: colour.hex,
            color: colour.isDark ? "rgba(255,255,255,0.92)" : "rgba(0,0,0,0.78)",
          }}
        >
          {colour.hex}
        </div>

        <div className="dominant-facts">
          <div>
            <div className="dominant-name">{colour.name}</div>
            <div className="dominant-share">
              {colour.percentage}% of {pixelsCounted.toLocaleString()} pixels counted
            </div>
          </div>

          <dl className="readouts">
            <div className="readout">
              <dt>RGB</dt>
              <dd>
                {r}, {g}, {b}
              </dd>
            </div>
            <div className="readout">
              <dt>Hex</dt>
              <dd>{colour.hex}</dd>
            </div>
            <div className="readout">
              <dt>Pixels</dt>
              <dd>{colour.count.toLocaleString()}</dd>
            </div>
            <div className="readout">
              <dt>Luminance</dt>
              <dd>{colour.luminance.toFixed(3)}</dd>
            </div>
          </dl>

          <button type="button" className="copy-button" onClick={copy}>
            {copied ? "Copied" : "Copy hex"}
          </button>
        </div>
      </div>
    </div>
  );
}
