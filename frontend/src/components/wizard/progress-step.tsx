"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api, subscribeToProgress } from "@/lib/api";
import type { Usage } from "@/lib/schemas";
import {
  Alert,
  Button,
  Card,
  ProgressBar,
  Spinner,
  formatTokens,
  formatUsd,
} from "@/components/ui/primitives";

const STAGES = [
  { id: "unzip", label: "Unzipping" },
  { id: "scan", label: "Scanning" },
  { id: "parsing", label: "Parsing" },
  { id: "summaries", label: "Building summaries" },
  { id: "top_flow", label: "Building top flow" },
  { id: "deeper_levels", label: "Building deeper levels" },
] as const;

export function ProgressStep({ projectId }: { projectId: string }) {
  const [stage, setStage] = useState<string>("parsing");
  const [percent, setPercent] = useState(4);
  const [item, setItem] = useState<string>("Reading your project");
  const [usage, setUsage] = useState<Usage | null>(null);
  const [graphReady, setGraphReady] = useState(false);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState<string | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    const unsubscribe = subscribeToProgress(projectId, ({ type, data }) => {
      const nextPercent = typeof data.percent === "number" ? data.percent : undefined;
      if (nextPercent !== undefined) setPercent(nextPercent);
      switch (type) {
        case "stage":
          if (typeof data.stage === "string") setStage(data.stage);
          if (typeof data.label === "string") setItem(data.label);
          break;
        case "progress":
          if (typeof data.item === "string") setItem(data.item);
          break;
        case "usage":
          setUsage(data as unknown as Usage);
          break;
        case "nodes":
          setItem("Drawing the flow");
          break;
        case "graph_ready":
          setGraphReady(true);
          break;
        case "done":
          setFinished(true);
          setPercent(100);
          break;
        case "limit_reached":
          setPaused(typeof data.message === "string" ? data.message : "Cost limit reached.");
          break;
        case "cancelled":
          if (!cancelled.current) setError("Analysis was cancelled.");
          break;
        case "error":
          setError(typeof data.message === "string" ? data.message : "Analysis failed.");
          break;
        default:
          break;
      }
    });
    return unsubscribe;
  }, [projectId]);

  useEffect(() => {
    // The stream may connect a beat after the run starts; a first poll fills the gap.
    void (async () => {
      const project = await api.getProject(projectId).catch(() => null);
      if (project?.status === "ready") {
        setFinished(true);
        setGraphReady(true);
        setPercent(100);
      }
      const totals = await api.usage(projectId).catch(() => null);
      if (totals) setUsage(totals);
    })();
  }, [projectId]);

  const activeIndex = useMemo(() => {
    const index = STAGES.findIndex((s) => s.id === stage);
    return index === -1 ? 2 : index;
  }, [stage]);

  const cancel = async () => {
    cancelled.current = true;
    await api.cancelAnalysis(projectId);
    setError("Analysis cancelled. You can still open whatever was built.");
  };

  return (
    <div className="flex flex-col gap-5">
      <Card className="p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-display text-lg font-semibold">
            {finished ? "Your flow is ready" : "Reading your project"}
          </h2>
          <span className="tabular text-sm text-muted">{Math.round(percent)}%</span>
        </div>
        <div className="mt-3">
          <ProgressBar value={percent} label="Analysis progress" />
        </div>
        <ol className="mt-4 grid gap-2 sm:grid-cols-2">
          {STAGES.map((entry, index) => {
            const state =
              finished || index < activeIndex ? "done" : index === activeIndex ? "active" : "todo";
            return (
              <li key={entry.id} className="flex items-center gap-2 text-sm">
                <span
                  aria-hidden="true"
                  className={`flex size-5 items-center justify-center rounded-full border text-[10px] font-bold ${
                    state === "done"
                      ? "border-success bg-success-soft text-success"
                      : state === "active"
                        ? "border-accent bg-accent-soft text-accent"
                        : "border-border text-faint"
                  }`}
                >
                  {state === "done" ? "✓" : index + 1}
                </span>
                <span className={state === "todo" ? "text-faint" : "text-text"}>{entry.label}</span>
                {state === "active" && !finished ? <Spinner className="text-accent" /> : null}
              </li>
            );
          })}
        </ol>
        {!finished ? <p className="mt-3 truncate text-sm text-muted">{item}</p> : null}

        <div className="mt-5 flex flex-wrap items-center gap-3">
          {graphReady ? (
            <Link
              href={`/projects/${projectId}/graph`}
              className="inline-flex items-center justify-center rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-contrast transition-colors hover:bg-accent-hover"
            >
              {finished ? "Open the flow" : "Open the flow so far"}
            </Link>
          ) : (
            <span className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-semibold text-faint">
              <Spinner /> Building the first level
            </span>
          )}
          {!finished ? (
            <Button variant="ghost" onClick={cancel}>
              Cancel
            </Button>
          ) : null}
        </div>
      </Card>

      <Card className="p-5">
        <h3 className="eyebrow">Spend so far</h3>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
          <Stat label="Cost" value={formatUsd(usage?.cost_usd ?? 0)} />
          <Stat label="Calls" value={String(usage?.calls ?? 0)} />
          <Stat label="Input" value={formatTokens(usage?.input_tokens ?? 0)} />
          <Stat label="Output" value={formatTokens(usage?.output_tokens ?? 0)} />
          <Stat label="From cache" value={formatTokens(usage?.cache_read_tokens ?? 0)} />
        </dl>
      </Card>

      {paused ? (
        <Alert tone="warning" title="Paused">
          {paused}
        </Alert>
      ) : null}
      {error ? <Alert tone="error">{error}</Alert> : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-0.5 font-display text-lg font-semibold tabular">{value}</dd>
    </div>
  );
}
