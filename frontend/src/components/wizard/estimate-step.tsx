"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Estimate, Project } from "@/lib/schemas";
import { Alert, Button, Card, Spinner, formatTokens, formatUsd } from "@/components/ui/primitives";
import type { ConnectionChoice } from "./connect-step";

const SKIP_LABELS: Record<string, string> = {
  ignored_dir: "folders of other people's code",
  gitignore: "files your project ignores",
  lock_file: "lock files",
  binary: "binary files",
  media: "images and media",
  generated: "generated files",
  minified: "minified files",
  too_large: "very large files",
  unreadable: "unreadable files",
};

export function EstimateStep({
  project,
  choice,
  onStarted,
}: {
  project: Project;
  choice: ConnectionChoice;
  onStarted: () => void;
}) {
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const result = await api.estimate(project.id, {
          model_id: choice.modelId,
          smart_mix: choice.smartMix,
          deep_model_id: choice.deepModelId,
        });
        if (!cancelled) setEstimate(result.estimate);
      } catch (err) {
        if (!cancelled)
          setError(err instanceof ApiError ? err.message : "Could not work out the cost.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [project.id, choice.modelId, choice.smartMix, choice.deepModelId]);

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      await api.startAnalysis(project.id, {
        model_id: choice.modelId,
        smart_mix: choice.smartMix,
        deep_model_id: choice.deepModelId,
      });
      onStarted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the analysis.");
      setStarting(false);
    }
  };

  const scan = project.scan;
  const languages = Object.entries(scan?.languages ?? {})
    .filter(([name]) => name !== "text")
    .sort((a, b) => b[1].files - a[1].files);
  const skipped = Object.entries(scan?.skipped_counts ?? {}).sort((a, b) => b[1] - a[1]);
  const needsConfirm = estimate?.over_limit ?? false;

  return (
    <div className="flex flex-col gap-5">
      <Card className="p-5">
        <h2 className="font-display text-lg font-semibold">What we found</h2>
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          <Stat label="Files to read" value={String(scan?.code_file_count ?? 0)} />
          <Stat label="Functions" value={String(scan?.function_count ?? "—")} />
          <Stat label="Classes" value={String(scan?.class_count ?? "—")} />
          <Stat label="Languages" value={languages.length ? String(languages.length) : "—"} />
        </dl>
        {languages.length ? (
          <ul className="mt-4 flex flex-wrap gap-2">
            {languages.map(([name, stat]) => (
              <li
                key={name}
                className="rounded-full border border-border bg-sunken px-2.5 py-1 text-xs font-medium capitalize"
              >
                {name} · {stat.files}
              </li>
            ))}
          </ul>
        ) : null}
        {scan?.frameworks.length ? (
          <p className="mt-3 text-sm text-muted">Libraries spotted: {scan.frameworks.join(", ")}</p>
        ) : null}
        {skipped.length ? (
          <p className="mt-3 text-sm text-muted">
            Skipped:{" "}
            {skipped
              .slice(0, 5)
              .map(([reason, count]) => `${count} ${SKIP_LABELS[reason] ?? reason}`)
              .join(", ")}
            .
          </p>
        ) : null}
      </Card>

      <Card className="p-5">
        <h2 className="font-display text-lg font-semibold">What it will cost</h2>
        {loading ? (
          <p className="mt-3 flex items-center gap-2 text-sm text-muted">
            <Spinner /> Measuring a sample of your code…
          </p>
        ) : estimate ? (
          <>
            <p className="mt-2 font-display text-3xl font-semibold tabular">
              {formatUsd(estimate.low_usd)} – {formatUsd(estimate.high_usd)}
            </p>
            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
              <Stat label="Claude calls" value={String(estimate.calls)} />
              <Stat label="Input tokens" value={formatTokens(estimate.input_tokens)} />
              <Stat label="Output tokens" value={formatTokens(estimate.output_tokens)} />
              <Stat label="Reused from cache" value={formatTokens(estimate.cached_input_tokens)} />
            </dl>
            <p className="mt-3 text-sm text-muted">
              Big picture with <strong>{estimate.top_model}</strong>
              {estimate.deep_model !== estimate.top_model ? (
                <>
                  , small details with <strong>{estimate.deep_model}</strong>
                </>
              ) : null}
              . You are charged by Anthropic, not by this app.
            </p>
            {needsConfirm ? (
              <div className="mt-4">
                <Alert tone="warning" title="This is above your cost limit">
                  The estimate is higher than the limit of {formatUsd(estimate.limit_usd)} set for
                  this server. Analysis will pause if it reaches the limit.
                  <label className="mt-2 flex items-center gap-2 font-medium">
                    <input
                      type="checkbox"
                      id="confirm-cost"
                      checked={confirmed}
                      onChange={(event) => setConfirmed(event.target.checked)}
                      className="size-4 accent-[var(--warning)]"
                    />
                    I understand and want to continue
                  </label>
                </Alert>
              </div>
            ) : null}
          </>
        ) : null}
        {error ? (
          <div className="mt-4">
            <Alert tone="error">{error}</Alert>
          </div>
        ) : null}
        <div className="mt-5">
          <Button
            onClick={start}
            loading={starting}
            disabled={loading || (needsConfirm && !confirmed)}
          >
            Start analysis
          </Button>
        </div>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-0.5 font-display text-xl font-semibold tabular">{value}</dd>
    </div>
  );
}
