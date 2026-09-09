import type { AnalysisOptions, Method } from "../types";
import { DEFAULT_OPTIONS } from "../types";

interface Props {
  options: AnalysisOptions;
  onChange: (next: AnalysisOptions) => void;
  disabled: boolean;
}

/** Preset exclusions, expressed as the HSV thresholds they map to. */
const EXCLUSIONS = [
  {
    key: "white",
    label: "Ignore near-white",
    swatch: "#FFFFFF",
    // 0.85 rather than 1.0 so off-whites and paper textures are caught too --
    // that is what people mean by "a white background".
    apply: (o: AnalysisOptions) => ({ ...o, maxLightness: 0.85 }),
    clear: (o: AnalysisOptions) => ({ ...o, maxLightness: 1 }),
    isOn: (o: AnalysisOptions) => o.maxLightness < 1,
  },
  {
    key: "black",
    label: "Ignore near-black",
    swatch: "#000000",
    apply: (o: AnalysisOptions) => ({ ...o, minLightness: 0.15 }),
    clear: (o: AnalysisOptions) => ({ ...o, minLightness: 0 }),
    isOn: (o: AnalysisOptions) => o.minLightness > 0,
  },
  {
    key: "grey",
    label: "Ignore washed-out",
    swatch: "#8A8F96",
    apply: (o: AnalysisOptions) => ({ ...o, minSaturation: 0.15 }),
    clear: (o: AnalysisOptions) => ({ ...o, minSaturation: 0 }),
    isOn: (o: AnalysisOptions) => o.minSaturation > 0,
  },
] as const;

/**
 * The settings panel.
 *
 * Every control maps to one backend parameter, and changing any of them
 * re-runs the analysis. The colour exclusions are presented as three plain
 * checkboxes rather than raw HSV sliders: "ignore near-white" is a thing people
 * want, whereas "maximum value 0.85" is an implementation detail.
 */
export default function Controls({ options, onChange, disabled }: Props) {
  const set = <K extends keyof AnalysisOptions>(key: K, value: AnalysisOptions[K]) =>
    onChange({ ...options, [key]: value });

  const isDefault = JSON.stringify(options) === JSON.stringify(DEFAULT_OPTIONS);

  return (
    <div className={`panel${disabled ? " working" : ""}`}>
      <h2>Settings</h2>

      <div className="field">
        {/* A <label> may only label a form control. Pointing one at a button
            makes that button announce itself as "Method" to a screen reader,
            hiding which option it actually is. The group carries the name
            instead, and each button keeps its own. */}
        <span className="field-heading">Method</span>
        <div className="segmented" role="group" aria-label="Counting method">
          {(
            [
              ["histogram", "Histogram"],
              ["kmeans", "k-means"],
            ] as [Method, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              id={`method-${value}`}
              type="button"
              aria-pressed={options.method === value}
              onClick={() => set("method", value)}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="panel-note">
          {options.method === "histogram"
            ? "Rounds colours onto a fixed grid and counts the fullest cell. Fast and exact."
            : "Finds natural colour groupings rather than using a fixed grid. Seeded, so results repeat."}
        </p>
      </div>

      {options.method === "histogram" ? (
        <div className="field">
          <label htmlFor="bucket">
            Bucket size
            <span className="value">{options.bucketSize}</span>
          </label>
          <input
            id="bucket"
            type="range"
            min={2}
            max={64}
            step={2}
            value={options.bucketSize}
            onChange={(event) => set("bucketSize", Number(event.target.value))}
          />
          <p className="panel-note">
            How much precision to discard before counting. Low keeps shades apart;
            high merges them together.
          </p>
        </div>
      ) : null}

      <div className="field">
        <label htmlFor="topn">
          Colours to return
          <span className="value">{options.topN}</span>
        </label>
        <input
          id="topn"
          type="range"
          min={1}
          max={12}
          value={options.topN}
          onChange={(event) => set("topN", Number(event.target.value))}
        />
      </div>

      <div className="field">
        <label htmlFor="maxdim">
          Analysis resolution
          <span className="value">{options.maxDimension}px</span>
        </label>
        <input
          id="maxdim"
          type="range"
          min={100}
          max={1200}
          step={50}
          value={options.maxDimension}
          onChange={(event) => set("maxDimension", Number(event.target.value))}
        />
        <p className="panel-note">
          Longest edge the image is shrunk to first. Dominant colour is a
          statistical property, so sampling costs accuracy you cannot see.
        </p>
      </div>

      <div className="field">
        <span className="field-heading">Exclude colours</span>
        {EXCLUSIONS.map((exclusion) => {
          const on = exclusion.isOn(options);
          return (
            <label className="toggle" key={exclusion.key}>
              <input
                type="checkbox"
                checked={on}
                onChange={() =>
                  onChange(on ? exclusion.clear(options) : exclusion.apply(options))
                }
              />
              {exclusion.label}
              <span className="swatch-dot" style={{ background: exclusion.swatch }} />
            </label>
          );
        })}
      </div>

      <button
        type="button"
        className="reset"
        onClick={() => onChange(DEFAULT_OPTIONS)}
        disabled={isDefault}
      >
        Reset to defaults
      </button>
    </div>
  );
}
