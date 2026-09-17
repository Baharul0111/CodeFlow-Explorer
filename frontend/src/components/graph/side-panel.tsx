"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { GraphNode, Snippet } from "@/lib/schemas";
import { Button, Spinner } from "@/components/ui/primitives";
import { KIND_LABELS, KIND_STYLE } from "./node-styles";

export function SidePanel({
  projectId,
  node,
  onClose,
  onGoDeeper,
  busy,
}: {
  projectId: string;
  node: GraphNode | null;
  onClose: () => void;
  onGoDeeper: (id: string) => void;
  busy: boolean;
}) {
  // The snippet is cached against the reference it belongs to, so switching nodes shows nothing
  // stale while the new one loads — no synchronous reset needed.
  const [loaded, setLoaded] = useState<{ key: string; snippet: Snippet | null } | null>(null);
  const ref = node?.code_refs[0] ?? null;
  const refKey = ref ? `${ref.file}:${ref.start_line}:${ref.end_line}` : "";

  useEffect(() => {
    if (!refKey || !ref) return;
    let cancelled = false;
    void api
      .snippet(projectId, ref.file, ref.start_line, ref.end_line)
      .then((result) => {
        if (!cancelled) setLoaded({ key: refKey, snippet: result });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ key: refKey, snippet: null });
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, refKey, ref]);

  const snippet = loaded?.key === refKey ? loaded.snippet : null;
  const loading = Boolean(refKey) && loaded?.key !== refKey;

  if (!node) return null;
  const style = KIND_STYLE[node.kind];

  return (
    <aside
      aria-label="Details"
      className="flex w-full shrink-0 flex-col border-t border-border bg-surface lg:h-full lg:w-[380px] lg:border-l lg:border-t-0"
    >
      <header className="flex items-start gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <p
            className="text-[10px] font-bold uppercase tracking-wider"
            style={{ color: style.text }}
          >
            {KIND_LABELS[node.kind]}
          </p>
          <h2 className="mt-0.5 font-display text-lg font-semibold leading-tight">{node.title}</h2>
        </div>
        <Button variant="ghost" onClick={onClose} aria-label="Close details" className="px-2 py-1">
          ✕
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <p className="text-sm leading-relaxed text-text">{node.explanation}</p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <ListBlock title="Takes in" items={node.inputs} empty="Nothing comes in here" />
          <ListBlock title="Gives out" items={node.outputs} empty="Nothing comes out here" />
        </div>

        {node.code_refs.length ? (
          <div className="mt-5">
            <h3 className="eyebrow">Where this lives in the code</h3>
            <ul className="mt-2 flex flex-col gap-1">
              {node.code_refs.map((codeRef, index) => (
                <li
                  key={`${codeRef.file}-${codeRef.start_line}-${index}`}
                  className="font-mono text-xs text-muted"
                >
                  {codeRef.file}
                  <span className="text-faint">
                    :{codeRef.start_line}
                    {codeRef.end_line !== codeRef.start_line ? `–${codeRef.end_line}` : ""}
                  </span>
                  {codeRef.symbol ? <span className="text-accent"> · {codeRef.symbol}</span> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {loading ? (
          <p className="mt-4 flex items-center gap-2 text-sm text-muted">
            <Spinner /> Loading the code…
          </p>
        ) : snippet ? (
          <figure className="mt-3 overflow-hidden rounded-lg border border-border bg-sunken">
            <figcaption className="border-b border-border px-3 py-1.5 font-mono text-[11px] text-faint">
              {snippet.file}:{snippet.start_line}
            </figcaption>
            <div className="max-h-72 overflow-auto">
              <pre className="min-w-full p-3 font-mono text-[11.5px] leading-relaxed">
                <code>
                  {snippet.code.split("\n").map((line, index) => (
                    <span key={index} className="grid grid-cols-[3rem_1fr] gap-2">
                      <span className="select-none text-right text-faint tabular">
                        {snippet.start_line + index}
                      </span>
                      <span className="whitespace-pre text-text">{line}</span>
                    </span>
                  ))}
                </code>
              </pre>
            </div>
          </figure>
        ) : null}

        {node.error ? (
          <p className="mt-4 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
            {node.error}
          </p>
        ) : null}
      </div>

      <footer className="border-t border-border px-4 py-3">
        {node.has_children ? (
          <Button onClick={() => onGoDeeper(node.id)} loading={busy} className="w-full">
            Go deeper
          </Button>
        ) : (
          <p className="text-center text-sm text-muted">
            This is the smallest step — there is nothing inside it.
          </p>
        )}
      </footer>
    </aside>
  );
}

function ListBlock({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div>
      <h3 className="eyebrow">{title}</h3>
      {items.length ? (
        <ul className="mt-1.5 flex flex-col gap-1">
          {items.map((item, index) => (
            <li key={index} className="text-sm text-text">
              • {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1.5 text-sm text-faint">{empty}</p>
      )}
    </div>
  );
}
