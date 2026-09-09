import { useRef, useState } from "react";
import type { DragEvent } from "react";

import type { SampleImage } from "../types";

interface Props {
  samples: SampleImage[];
  activeSampleId: string | null;
  onFile: (file: File) => void;
  onSample: (sample: SampleImage) => void;
}

/** Largest upload the backend will accept, mirrored here to fail fast. */
const MAX_BYTES = 12 * 1024 * 1024;

/**
 * Image input: drag-and-drop, click-to-browse, or one of the bundled samples.
 *
 * Obvious problems (wrong file type, oversized file) are caught here so the user
 * gets an instant answer rather than waiting on a round trip that can only fail.
 * The backend re-checks both regardless -- a client-side check is a convenience,
 * never a guarantee.
 */
export default function Uploader({ samples, activeSampleId, onFile, onSample }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  function accept(file: File | undefined) {
    if (!file) return;

    if (!file.type.startsWith("image/")) {
      setLocalError(`"${file.name}" does not look like an image.`);
      return;
    }
    if (file.size > MAX_BYTES) {
      setLocalError(
        `That file is ${(file.size / 1_048_576).toFixed(1)} MB. The limit is 12 MB.`,
      );
      return;
    }

    setLocalError(null);
    onFile(file);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    accept(event.dataTransfer.files[0]);
  }

  return (
    <div className="panel">
      <h2>Image</h2>

      <div
        className={`dropzone${dragging ? " dragging" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <strong>Drop an image here</strong>
        <span>or click to browse &middot; JPG, PNG, GIF, WEBP &middot; max 12 MB</span>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(event) => {
          accept(event.target.files?.[0]);
          // Clearing the value lets the same file be re-selected, which would
          // otherwise fire no change event the second time.
          event.target.value = "";
        }}
      />

      {localError && (
        <p className="panel-note" style={{ color: "var(--danger)" }}>
          {localError}
        </p>
      )}

      <p className="panel-note">Or try a sample with a known answer:</p>

      <div className="samples">
        {samples.map((sample) => (
          <button
            key={sample.id}
            type="button"
            className={`sample${activeSampleId === sample.id ? " active" : ""}`}
            onClick={() => {
              setLocalError(null);
              onSample(sample);
            }}
            title={sample.description}
          >
            <img src={sample.url} alt="" loading="lazy" />
            <small>{sample.name}</small>
          </button>
        ))}
      </div>
    </div>
  );
}
