"use client";

import { useCallback, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Project } from "@/lib/schemas";
import { Alert, Button, Card, ProgressBar, formatBytes } from "@/components/ui/primitives";

export function UploadStep({ onUploaded }: { onUploaded: (project: Project) => void }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const choose = useCallback((picked: File | undefined) => {
    setError(null);
    if (!picked) return;
    if (!picked.name.toLowerCase().endsWith(".zip")) {
      setError("Please choose a .zip file containing your project.");
      return;
    }
    setFile(picked);
  }, []);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setProgress(0);
    try {
      const project = await api.uploadProject(file, (fraction) => setProgress(fraction * 100));
      onUploaded(project);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Card
        className={`relative flex flex-col items-center gap-3 border-2 border-dashed px-6 py-12 text-center transition-colors ${
          dragging ? "border-accent bg-accent-soft" : "border-border"
        }`}
      >
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            choose(event.dataTransfer.files[0]);
          }}
          className="absolute inset-0"
          aria-hidden="true"
        />
        <p className="font-display text-lg font-semibold">Drop your project zip here</p>
        <p className="max-w-sm text-sm text-muted">
          Everything stays on this server. Your code is read as text and never run.
        </p>
        <input
          ref={inputRef}
          id="project-zip"
          type="file"
          accept=".zip,application/zip"
          className="sr-only"
          onChange={(event) => choose(event.target.files?.[0])}
        />
        <Button
          variant="secondary"
          className="relative z-10"
          onClick={() => inputRef.current?.click()}
        >
          Choose a file
        </Button>
      </Card>

      {file ? (
        <Card className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{file.name}</p>
            <p className="tabular text-sm text-muted">{formatBytes(file.size)}</p>
          </div>
          <Button onClick={upload} loading={busy}>
            {busy ? "Unpacking…" : "Upload and scan"}
          </Button>
          {busy ? (
            <div className="w-full">
              <ProgressBar value={progress} label="Upload progress" />
              <p className="mt-1 tabular text-xs text-muted">{Math.round(progress)}% uploaded</p>
            </div>
          ) : null}
        </Card>
      ) : null}

      {error ? <Alert tone="error">{error}</Alert> : null}
    </div>
  );
}
