"use client";

import { useEffect, useState } from "react";
import type { NodeKind } from "@/lib/schemas";

const KINDS: NodeKind[] = ["start", "process", "decision", "datastore", "external", "output"];

function readColors(): Record<NodeKind, string> {
  const styles = getComputedStyle(document.documentElement);
  const entries = KINDS.map(
    (kind) => [kind, styles.getPropertyValue(`--node-${kind}`).trim() || "#888"] as const,
  );
  return Object.fromEntries(entries) as Record<NodeKind, string>;
}

const FALLBACK: Record<NodeKind, string> = {
  start: "#18794e",
  process: "#1f5fb0",
  decision: "#9a5b00",
  datastore: "#6b3fa0",
  external: "#52607a",
  output: "#b4231f",
};

/**
 * Real colour values for the node kinds.
 *
 * The minimap paints with SVG `fill` attributes, which cannot resolve `var(--…)`, so the tokens
 * have to be read from the document — and re-read whenever the theme changes.
 */
export function useNodeColors(): Record<NodeKind, string> {
  const [colors, setColors] = useState<Record<NodeKind, string>>(FALLBACK);

  useEffect(() => {
    const update = () => setColors(readColors());
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", update);
    };
  }, []);

  return colors;
}
