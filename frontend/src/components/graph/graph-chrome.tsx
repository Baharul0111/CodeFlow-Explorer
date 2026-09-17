"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { GraphNode, SearchHit } from "@/lib/schemas";
import { Button } from "@/components/ui/primitives";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { KIND_SHORT, KIND_STYLE } from "./node-styles";
import type { NodeKind } from "@/lib/schemas";

export function Breadcrumbs({
  trail,
  onJump,
}: {
  trail: GraphNode[];
  onJump: (id: string | null) => void;
}) {
  return (
    <nav aria-label="Where you are" className="flex min-w-0 items-center gap-1 text-sm">
      <button
        type="button"
        onClick={() => onJump(null)}
        className="shrink-0 rounded px-1.5 py-0.5 font-medium text-muted hover:bg-sunken hover:text-text"
      >
        System
      </button>
      {trail.map((node) => (
        <span key={node.id} className="flex min-w-0 items-center gap-1">
          <span aria-hidden="true" className="text-faint">
            ›
          </span>
          <button
            type="button"
            onClick={() => onJump(node.id)}
            className="truncate rounded px-1.5 py-0.5 font-medium text-muted hover:bg-sunken hover:text-text"
          >
            {node.title}
          </button>
        </span>
      ))}
    </nav>
  );
}

export function SearchBox({
  projectId,
  onPick,
}: {
  projectId: string;
  onPick: (hit: SearchHit) => void;
}) {
  const [query, setQuery] = useState("");
  // Results are stored with the query that produced them, so a stale list is never shown.
  const [results, setResults] = useState<{ query: string; hits: SearchHit[] }>({
    query: "",
    hits: [],
  });
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const trimmed = query.trim();

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (trimmed.length < 2) return;
    timer.current = setTimeout(() => {
      void api
        .search(projectId, trimmed)
        .then((found) => {
          setResults({ query: trimmed, hits: found });
          setOpen(true);
        })
        .catch(() => setResults({ query: trimmed, hits: [] }));
    }, 180);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [projectId, trimmed]);

  const hits = results.query === trimmed ? results.hits : [];

  return (
    <div className="relative">
      <input
        id="graph-search"
        type="search"
        value={query}
        placeholder="Search steps or files"
        aria-label="Search the flow"
        onChange={(event) => setQuery(event.target.value)}
        onFocus={() => setOpen(hits.length > 0)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="w-44 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text placeholder:text-faint sm:w-60"
      />
      {open && hits.length ? (
        <ul className="absolute right-0 z-20 mt-1 max-h-80 w-80 overflow-auto rounded-lg border border-border bg-surface py-1 shadow-[var(--shadow-md)]">
          {hits.map((hit) => (
            <li key={hit.node_id}>
              <button
                type="button"
                onMouseDown={(event) => {
                  event.preventDefault();
                  onPick(hit);
                  setOpen(false);
                }}
                className="flex w-full flex-col items-start px-3 py-1.5 text-left hover:bg-sunken"
              >
                <span className="text-sm font-medium">{hit.title}</span>
                <span className="truncate font-mono text-[11px] text-faint">{hit.subtitle}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function Legend() {
  const kinds = Object.keys(KIND_SHORT) as NodeKind[];
  return (
    <ul className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {kinds.map((kind) => (
        <li key={kind} className="flex items-center gap-1.5 text-[11px] text-muted">
          <span
            aria-hidden="true"
            className="size-2.5 rounded-sm"
            style={{ background: KIND_STYLE[kind].border }}
          />
          {KIND_SHORT[kind]}
        </li>
      ))}
    </ul>
  );
}

function ShareButton({ projectId }: { projectId: string }) {
  const [copied, setCopied] = useState(false);

  const copyLink = async () => {
    const link = `${window.location.origin}/projects/${projectId}/graph`;
    try {
      await navigator.clipboard.writeText(link);
    } catch {
      window.prompt("Copy this link:", link);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Button variant="secondary" onClick={copyLink} className="px-2.5 py-1.5 text-xs">
      {copied ? "Link copied" : "Copy link"}
    </Button>
  );
}

export function GraphToolbar({
  projectId,
  projectName,
  onExportPng,
  children,
}: {
  projectId: string;
  projectName: string;
  onExportPng: () => void;
  children?: React.ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-border bg-surface px-4 py-2.5">
      <Link href="/projects" className="font-display text-sm font-semibold hover:text-accent">
        CodeFlow
      </Link>
      <span aria-hidden="true" className="text-faint">
        /
      </span>
      <span className="truncate text-sm font-medium">{projectName}</span>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {children}
        <ShareButton projectId={projectId} />
        <a
          href={api.exportPageUrl(projectId)}
          className="rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-accent-contrast hover:bg-accent-hover"
          download
          title="A single file you can send to anyone — it opens and expands without this server"
        >
          Share as page
        </a>
        <Button variant="secondary" onClick={onExportPng} className="px-2.5 py-1.5 text-xs">
          PNG
        </Button>
        <a
          href={api.exportUrl(projectId)}
          className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs font-semibold text-text hover:bg-sunken"
          download
        >
          JSON
        </a>
        <ThemeToggle />
      </div>
    </header>
  );
}
