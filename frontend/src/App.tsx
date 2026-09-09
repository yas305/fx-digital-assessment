import { useCallback, useEffect, useRef, useState } from "react";

import AlgorithmAnimation from "./components/AlgorithmAnimation";
import Controls from "./components/Controls";
import DistributionChart from "./components/DistributionChart";
import DominantCard from "./components/DominantCard";
import Palette from "./components/Palette";
import StatsPanel from "./components/StatsPanel";
import Uploader from "./components/Uploader";
import {
  ApiError,
  analyseSample,
  analyseUpload,
  checkHealth,
  explainSample,
  explainUpload,
  fetchSamples,
} from "./lib/api";
import type {
  AnalysisOptions,
  AnalysisResponse,
  ExplainResponse,
  SampleImage,
} from "./types";
import { DEFAULT_OPTIONS } from "./types";

/** Whichever image is currently being analysed. */
type Source =
  | { kind: "sample"; sample: SampleImage }
  | { kind: "file"; file: File; previewUrl: string };

/**
 * Sliders fire a change on every pixel of movement. Waiting for a short pause
 * before calling the API turns a drag across the bucket-size slider into one
 * request instead of thirty.
 */
const DEBOUNCE_MS = 250;

/** The two things the right-hand column can show. */
type View = "results" | "algorithm";

export default function App() {
  const [samples, setSamples] = useState<SampleImage[]>([]);
  const [source, setSource] = useState<Source | null>(null);
  const [options, setOptions] = useState<AnalysisOptions>(DEFAULT_OPTIONS);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [view, setView] = useState<View>("results");
  const [explanation, setExplanation] = useState<ExplainResponse | null>(null);
  const [explaining, setExplaining] = useState(false);

  // Tracks the in-flight request so a superseded one can be cancelled. Without
  // this, dragging a slider can let an early, slow response land after a later,
  // faster one and overwrite it with stale data.
  const inFlight = useRef<AbortController | null>(null);
  const explainInFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    checkHealth().then(setOnline);
    fetchSamples()
      .then(setSamples)
      .catch(() => {
        // A failed sample list is not fatal -- uploads still work -- and the
        // connection indicator already communicates that the API is unreachable.
      });
  }, []);

  // Object URLs for uploaded files are revoked when they are replaced, so
  // previews of discarded images do not accumulate in memory.
  useEffect(() => {
    return () => {
      if (source?.kind === "file") URL.revokeObjectURL(source.previewUrl);
    };
  }, [source]);

  const run = useCallback(
    async (currentSource: Source, currentOptions: AnalysisOptions) => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      setBusy(true);
      setError(null);

      try {
        const response =
          currentSource.kind === "sample"
            ? await analyseSample(currentSource.sample.id, currentOptions, controller.signal)
            : await analyseUpload(currentSource.file, currentOptions, controller.signal);

        setResult(response);
        setOnline(true);
      } catch (caught) {
        // An aborted request was deliberately replaced; it is not an error.
        if (caught instanceof DOMException && caught.name === "AbortError") return;

        if (caught instanceof ApiError) {
          setError(caught.message);
        } else {
          setError(
            "Could not reach the analysis service. Make sure the Python backend is " +
              "running on port 8000.",
          );
          setOnline(false);
        }
        setResult(null);
      } finally {
        // Only the newest request may clear the busy flag, or a cancelled
        // request finishing late would hide a spinner that is still needed.
        if (inFlight.current === controller) setBusy(false);
      }
    },
    [],
  );

  // Re-analyse whenever the image or any setting changes.
  useEffect(() => {
    if (!source) return;
    const timer = window.setTimeout(() => void run(source, options), DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [source, options, run]);

  const runExplain = useCallback(
    async (currentSource: Source, currentOptions: AnalysisOptions) => {
      explainInFlight.current?.abort();
      const controller = new AbortController();
      explainInFlight.current = controller;
      setExplaining(true);

      try {
        const response =
          currentSource.kind === "sample"
            ? await explainSample(currentSource.sample.id, currentOptions, controller.signal)
            : await explainUpload(currentSource.file, currentOptions, controller.signal);
        setExplanation(response);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        // The results view already surfaces API errors, and it shares this
        // image and these settings. Repeating the message here would just be
        // the same error twice.
        setExplanation(null);
      } finally {
        if (explainInFlight.current === controller) setExplaining(false);
      }
    },
    [],
  );

  // Only fetch the visualisation while its tab is open. It is a much larger
  // payload than the analysis, and requesting it on every slider movement
  // regardless of whether anyone is looking would be wasteful.
  useEffect(() => {
    if (!source || view !== "algorithm") return;
    const timer = window.setTimeout(() => void runExplain(source, options), DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [source, options, view, runExplain]);

  function chooseFile(file: File) {
    setSource({ kind: "file", file, previewUrl: URL.createObjectURL(file) });
  }

  const previewUrl =
    source?.kind === "file" ? source.previewUrl : source?.kind === "sample" ? source.sample.url : null;
  const activeSampleId = source?.kind === "sample" ? source.sample.id : null;

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>Dominant Colour Finder</h1>
          <p>
            Finds the most frequent colour in an image by grouping near-identical
            shades together and counting them. Python backend, TypeScript frontend.
          </p>
        </div>
        <span
          className={`status${online === true ? " online" : online === false ? " offline" : ""}`}
        >
          <span className="dot" />
          {online === null ? "Connecting" : online ? "Backend connected" : "Backend offline"}
        </span>
      </header>

      <div className="columns">
        <div className="stack">
          <Uploader
            samples={samples}
            activeSampleId={activeSampleId}
            onFile={chooseFile}
            onSample={(sample) => setSource({ kind: "sample", sample })}
          />

          {previewUrl && (
            <div className="panel">
              <h2>
                Preview{" "}
                {busy && <span className="spinner" style={{ marginLeft: 6, verticalAlign: -1 }} />}
              </h2>
              <img className="preview-image" src={previewUrl} alt="The image being analysed" />
              {source?.kind === "sample" && (
                <p className="panel-note">{source.sample.description}</p>
              )}
            </div>
          )}

          <Controls options={options} onChange={setOptions} disabled={busy} />
        </div>

        <div className="stack">
          {error && <div className="notice error">{error}</div>}

          {!source && !error && (
            <div className="empty-state">
              <h3>No image selected</h3>
              <p>
                Upload an image or pick one of the samples to see its dominant colour,
                full palette and colour distribution.
              </p>
            </div>
          )}

          {source && !error && (
            <div className="viewtabs" role="tablist" aria-label="View">
              {(
                [
                  ["results", "Results"],
                  ["algorithm", "How it works"],
                ] as [View, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={view === value}
                  onClick={() => setView(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {view === "algorithm" && source && !error && (
            explanation ? (
              <div className={explaining ? "working" : undefined}>
                <AlgorithmAnimation data={explanation} />
              </div>
            ) : (
              <div className="empty-state">
                <h3>
                  <span className="spinner" style={{ marginRight: 8, verticalAlign: -1 }} />
                  Preparing the walkthrough
                </h3>
                <p>Sampling real pixels and replaying the algorithm over them.</p>
              </div>
            )
          )}

          {view === "results" && result && (
            <div className={`stack${busy ? " working" : ""}`}>
              <DominantCard
                colour={result.dominant}
                pixelsCounted={result.filters.pixelsCounted}
              />

              <Palette palette={result.palette} />

              <div className="panel">
                <div className="chart-grid">
                  <DistributionChart
                    title="Hue distribution"
                    bins={result.hueDistribution}
                    labelEvery={2}
                    emptyMessage="No pixels are colourful enough to have a meaningful hue — this image is effectively greyscale."
                    note="Grey pixels are excluded, since they have no hue to place on the wheel."
                  />
                  <DistributionChart
                    title="Tonal range"
                    bins={result.toneDistribution}
                    emptyMessage="No tonal data available."
                    note="How the image's pixels spread from darkest to lightest."
                  />
                </div>
              </div>

              <StatsPanel result={result} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
