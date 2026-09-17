"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Graph, Project } from "@/lib/schemas";
import { Alert, Spinner } from "@/components/ui/primitives";
import { GraphCanvas } from "@/components/graph/graph-canvas";

export default function GraphPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [loadedProject, loadedGraph] = await Promise.all([
          api.getProject(projectId),
          api.getGraph(projectId),
        ]);
        if (cancelled) return;
        setProject(loadedProject);
        setGraph(loadedGraph);
      } catch {
        if (!cancelled) setError("Could not open this project.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return (
      <div className="mx-auto w-full max-w-lg px-4 py-16">
        <Alert tone="error">{error}</Alert>
        <Link href="/projects" className="mt-4 inline-block text-sm font-semibold text-accent">
          Back to your projects
        </Link>
      </div>
    );
  }

  if (!graph || !project) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted">
        <Spinner /> Opening the flow…
      </div>
    );
  }

  if (graph.nodes.length === 0) {
    return (
      <div className="mx-auto w-full max-w-lg px-4 py-16 text-center">
        <h1 className="font-display text-xl font-semibold">This project has no flow yet</h1>
        <p className="mt-2 text-sm text-muted">
          It was uploaded but never analysed, or the analysis was cancelled before the first level
          was built.
        </p>
        <Link
          href="/"
          className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-contrast"
        >
          Start a new analysis
        </Link>
      </div>
    );
  }

  return <GraphCanvas projectId={projectId} projectName={project.name} initialGraph={graph} />;
}
