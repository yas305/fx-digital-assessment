/**
 * TypeScript mirrors of the backend's response schemas.
 *
 * The Python models serialise to camelCase specifically so these can be written
 * idiomatically, with no field renaming in between. They are hand-maintained;
 * on a longer-lived project the honest move is to generate them from the
 * backend's OpenAPI schema (which FastAPI publishes at /openapi.json) so the two
 * cannot drift apart.
 */

export type Method = "histogram" | "kmeans";

export type RGB = [number, number, number];

export interface ColourResult {
  rgb: RGB;
  hex: string;
  /** Closest human-readable name, e.g. "Sky Blue". */
  name: string;
  count: number;
  /** Fraction of counted pixels, 0-1. */
  share: number;
  /** The same figure as a percentage, pre-rounded. */
  percentage: number;
  luminance: number;
  /** True when white text is more readable on this colour than black. */
  isDark: boolean;
  bucketRgb: RGB;
}

export interface HueBin {
  label: string;
  startDegrees: number;
  endDegrees: number;
  count: number;
  share: number;
  hex: string;
}

export interface ToneBin {
  label: string;
  count: number;
  share: number;
  hex: string;
}

export interface ImageInfo {
  filename: string | null;
  format: string;
  mode: string;
  width: number;
  height: number;
  totalPixels: number;
  sampledWidth: number;
  sampledHeight: number;
  sampledPixels: number;
  wasDownsampled: boolean;
  transparentDropped: number;
  fileSizeBytes: number | null;
}

export interface FilterSummary {
  active: boolean;
  removedLowSaturation: number;
  removedTooDark: number;
  removedTooLight: number;
  removedIgnored: number;
  totalRemoved: number;
  pixelsCounted: number;
}

export interface AnalysisStats {
  distinctColours: number;
  uniqueRawColours: number;
  averageSaturation: number;
  averageLightness: number;
  colourfulness: number;
  iterations: number | null;
  durationMs: number;
}

export interface OptionsEcho {
  method: Method;
  bucketSize: number;
  topN: number;
  maxDimension: number | null;
  minSaturation: number;
  minLightness: number;
  maxLightness: number;
  ignoreColours: string[];
  ignoreTolerance: number;
}

export interface AnalysisResponse {
  method: Method;
  dominant: ColourResult;
  palette: ColourResult[];
  hueDistribution: HueBin[];
  toneDistribution: ToneBin[];
  image: ImageInfo;
  filters: FilterSummary;
  stats: AnalysisStats;
  optionsUsed: OptionsEcho;
}

export interface SampleImage {
  id: string;
  name: string;
  description: string;
  url: string;
}

/* -------------------------------------------------------------------------
 * Algorithm visualisation
 *
 * These describe the genuine intermediate state of a run -- a sample of real
 * pixels from the image, and either their bucket assignments or the full
 * history of the k-means centres.
 * ---------------------------------------------------------------------- */

export interface ExplainPixel {
  rgb: RGB;
  hex: string;
  /** The colour after rounding. Histogram method only. */
  quantisedRgb: RGB | null;
  quantisedHex: string | null;
  /** Where this pixel sits in the source image, normalised to 0-1. */
  imagePosition: [number, number];
  /** Position in the 2D projection of colour space. k-means only. */
  colourPosition: [number, number] | null;
  /** Index into `buckets`, or -1 when the pixel falls outside the top N. */
  bucket: number;
}

export interface ExplainBucket {
  rgb: RGB;
  hex: string;
  name: string;
  bucketRgb: RGB;
  bucketHex: string;
  count: number;
  share: number;
  percentage: number;
}

export interface ExplainCentre {
  rgb: RGB;
  hex: string;
  position: [number, number];
  /** This centre's place in the final size ranking. */
  rank: number;
  share: number;
}

export interface ExplainIteration {
  step: number;
  /** True for the initial k-means++ seeding, which is chosen rather than computed. */
  isSeed: boolean;
  centres: ExplainCentre[];
  /** Which centre each sampled pixel belonged to at this step. */
  assignments: number[];
}

export interface ExplainResponse {
  method: Method;
  bucketSize: number;
  sampleSize: number;
  totalPixels: number;
  uniqueRawColours: number;
  distinctColours: number;
  pixels: ExplainPixel[];
  buckets: ExplainBucket[];
  /** k-means steps. Empty for the histogram method. */
  iterations: ExplainIteration[];
  dominant: ColourResult;
  image: ImageInfo;
}

/** Every knob the UI exposes, in one object so it can be sent as a unit. */
export interface AnalysisOptions {
  method: Method;
  bucketSize: number;
  topN: number;
  maxDimension: number;
  minSaturation: number;
  minLightness: number;
  maxLightness: number;
  ignoreColours: string[];
  ignoreTolerance: number;
}

export const DEFAULT_OPTIONS: AnalysisOptions = {
  method: "histogram",
  bucketSize: 16,
  topN: 6,
  maxDimension: 400,
  minSaturation: 0,
  minLightness: 0,
  maxLightness: 1,
  ignoreColours: [],
  ignoreTolerance: 24,
};
