import type { NodeKind } from "@/lib/schemas";

export const KIND_LABELS: Record<NodeKind, string> = {
  start: "Where information comes in",
  process: "Something is done",
  decision: "A choice is made",
  datastore: "Information is stored",
  external: "Another service is used",
  output: "What comes out",
};

export const KIND_SHORT: Record<NodeKind, string> = {
  start: "Start",
  process: "Step",
  decision: "Choice",
  datastore: "Storage",
  external: "Outside",
  output: "Output",
};

/** Each kind gets its own hue, border and accent bar — colour carries meaning here. */
export const KIND_STYLE: Record<NodeKind, { bg: string; border: string; text: string }> = {
  start: { bg: "var(--node-start-bg)", border: "var(--node-start)", text: "var(--node-start)" },
  process: {
    bg: "var(--node-process-bg)",
    border: "var(--node-process)",
    text: "var(--node-process)",
  },
  decision: {
    bg: "var(--node-decision-bg)",
    border: "var(--node-decision)",
    text: "var(--node-decision)",
  },
  datastore: {
    bg: "var(--node-datastore-bg)",
    border: "var(--node-datastore)",
    text: "var(--node-datastore)",
  },
  external: {
    bg: "var(--node-external-bg)",
    border: "var(--node-external)",
    text: "var(--node-external)",
  },
  output: { bg: "var(--node-output-bg)", border: "var(--node-output)", text: "var(--node-output)" },
};

export const EDGE_STYLE: Record<string, { stroke: string; dash?: string }> = {
  data: { stroke: "var(--border-strong)" },
  control: { stroke: "var(--text-faint)", dash: "6 4" },
  error: { stroke: "var(--node-output)", dash: "2 4" },
};
