/**
 * Thin client for the Python backend.
 *
 * Requests go to relative /api paths, which Vite proxies to the FastAPI server
 * in development and which would be served by the same origin in production.
 */

import type {
  AnalysisOptions,
  AnalysisResponse,
  ExplainResponse,
  SampleImage,
} from "../types";

/** Error carrying the backend's own message, so the UI can show something useful. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Pull a human-readable message out of a failed response.
 *
 * FastAPI returns `{ detail: string }` for our own errors, but validation
 * failures arrive as `{ detail: [{ msg, loc }] }`, and a crashed or missing
 * server returns no JSON at all. All three need to end up as a sentence.
 */
async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      const first = body.detail[0];
      if (first?.msg) {
        const field = Array.isArray(first.loc) ? first.loc.at(-1) : undefined;
        return field ? `${field}: ${first.msg}` : String(first.msg);
      }
    }
  } catch {
    // Body was not JSON; fall through to the status-based message.
  }
  return `Request failed (${response.status} ${response.statusText}).`;
}

/** Translate the options object into the query/form parameters the API expects. */
function toParams(options: AnalysisOptions): Record<string, string> {
  const params: Record<string, string> = {
    method: options.method,
    bucket_size: String(options.bucketSize),
    top_n: String(options.topN),
    max_dimension: String(options.maxDimension),
    min_saturation: String(options.minSaturation),
    min_lightness: String(options.minLightness),
    max_lightness: String(options.maxLightness),
    ignore_tolerance: String(options.ignoreTolerance),
  };
  if (options.ignoreColours.length > 0) {
    params.ignore_colours = options.ignoreColours.join(",");
  }
  return params;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch("/api/health");
    return response.ok;
  } catch {
    return false;
  }
}

export async function fetchSamples(): Promise<SampleImage[]> {
  const response = await fetch("/api/samples");
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  return response.json();
}

export async function analyseSample(
  sampleId: string,
  options: AnalysisOptions,
  signal?: AbortSignal,
): Promise<AnalysisResponse> {
  const query = new URLSearchParams(toParams(options));
  const response = await fetch(`/api/samples/${sampleId}/analyse?${query}`, {
    method: "POST",
    signal,
  });
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  return response.json();
}

export async function analyseUpload(
  file: File,
  options: AnalysisOptions,
  signal?: AbortSignal,
): Promise<AnalysisResponse> {
  const body = new FormData();
  body.append("file", file);
  for (const [key, value] of Object.entries(toParams(options))) {
    body.append(key, value);
  }

  const response = await fetch("/api/analyse", { method: "POST", body, signal });
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  return response.json();
}

/**
 * Fetch the step-by-step data behind the algorithm animation.
 *
 * The exclusion filters are forwarded but the ignore-list is not: the
 * visualisation is about how counting works, and a per-colour blocklist adds
 * cases to explain without adding anything to see.
 */
export async function explainSample(
  sampleId: string,
  options: AnalysisOptions,
  signal?: AbortSignal,
): Promise<ExplainResponse> {
  const query = new URLSearchParams(explainParams(options));
  const response = await fetch(`/api/samples/${sampleId}/explain?${query}`, {
    method: "POST",
    signal,
  });
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  return response.json();
}

export async function explainUpload(
  file: File,
  options: AnalysisOptions,
  signal?: AbortSignal,
): Promise<ExplainResponse> {
  const body = new FormData();
  body.append("file", file);
  for (const [key, value] of Object.entries(explainParams(options))) {
    body.append(key, value);
  }

  const response = await fetch("/api/explain", { method: "POST", body, signal });
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  return response.json();
}

function explainParams(options: AnalysisOptions): Record<string, string> {
  return {
    method: options.method,
    bucket_size: String(options.bucketSize),
    // The visualiser caps top-N lower than the analyser: past about eight
    // columns the animation is unreadable at any sensible canvas size.
    top_n: String(Math.min(options.topN, 8)),
    max_dimension: String(options.maxDimension),
    min_saturation: String(options.minSaturation),
    min_lightness: String(options.minLightness),
    max_lightness: String(options.maxLightness),
  };
}
