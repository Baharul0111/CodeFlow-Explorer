"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ProjectListItem } from "@/lib/schemas";
import { Alert, Button, Card, Spinner, formatUsd } from "@/components/ui/primitives";
import { ThemeToggle } from "@/components/ui/theme-toggle";

const STATUS_LABELS: Record<string, string> = {
  scanned: "Scanned, not analysed",
  queued: "Waiting to start",
  analysing: "Being read",
  ready: "Ready",
  paused: "Paused at the cost limit",
  cancelled: "Cancelled",
  error: "Something went wrong",
};

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    void api
      .listProjects()
      .then(setProjects)
      .catch(() => setError("Could not load your projects."));
  }, []);

  useEffect(load, [load]);

  const remove = async (id: string) => {
    await api.deleteProject(id).catch(() => setError("Could not delete that project."));
    load();
  };

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold">Your projects</h1>
          <p className="text-sm text-muted">
            Reopening a project costs nothing — the flow is already saved.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/"
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-accent-contrast hover:bg-accent-hover"
          >
            New project
          </Link>
          <ThemeToggle />
        </div>
      </header>

      {error ? <Alert tone="error">{error}</Alert> : null}

      {projects === null ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Loading…
        </p>
      ) : projects.length === 0 ? (
        <Card className="px-5 py-10 text-center">
          <p className="font-display text-lg font-semibold">Nothing here yet</p>
          <p className="mt-1 text-sm text-muted">
            Upload a project zip and it will show up in this list.
          </p>
          <Link
            href="/"
            className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-contrast"
          >
            Upload a project
          </Link>
        </Card>
      ) : (
        <ul className="flex flex-col gap-2">
          {projects.map((project) => (
            <Card as="li" key={project.id} className="flex flex-wrap items-center gap-4 px-4 py-3">
              <div className="min-w-0 flex-1">
                <Link
                  href={`/projects/${project.id}/graph`}
                  className="font-display text-base font-semibold hover:text-accent"
                >
                  {project.name}
                </Link>
                <p className="tabular text-sm text-muted">
                  {STATUS_LABELS[project.status] ?? project.status} · {project.file_count} files ·{" "}
                  {project.node_count} steps · {formatUsd(project.total_cost_usd)} spent
                </p>
              </div>
              <time className="text-xs text-faint" dateTime={project.created_at}>
                {new Date(project.created_at).toLocaleDateString()}
              </time>
              <Button variant="ghost" onClick={() => void remove(project.id)}>
                Delete
              </Button>
            </Card>
          ))}
        </ul>
      )}
    </div>
  );
}
