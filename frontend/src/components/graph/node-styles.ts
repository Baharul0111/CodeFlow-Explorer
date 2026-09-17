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
export const KIND_STYLE: Record<
  NodeKind,
  { bg: string; border: string; line: string; text: string }
> = {
  start: {
    bg: "var(--node-start-bg)",
    border: "var(--node-start)",
    line: "var(--node-start-line)",
    text: "var(--node-start)",
  },
  process: {
    bg: "var(--node-process-bg)",
    border: "var(--node-process)",
    line: "var(--node-process-line)",
    text: "var(--node-process)",
  },
  decision: {
    bg: "var(--node-decision-bg)",
    border: "var(--node-decision)",
    line: "var(--node-decision-line)",
    text: "var(--node-decision)",
  },
  datastore: {
    bg: "var(--node-datastore-bg)",
    border: "var(--node-datastore)",
    line: "var(--node-datastore-line)",
    text: "var(--node-datastore)",
  },
  external: {
    bg: "var(--node-external-bg)",
    border: "var(--node-external)",
    line: "var(--node-external-line)",
    text: "var(--node-external)",
  },
  output: {
    bg: "var(--node-output-bg)",
    border: "var(--node-output)",
    line: "var(--node-output-line)",
    text: "var(--node-output)",
  },
};

export const EDGE_STYLE: Record<string, { stroke: string; dash?: string }> = {
  data: { stroke: "var(--border-strong)" },
  control: { stroke: "var(--text-faint)", dash: "6 4" },
  error: { stroke: "var(--node-output)", dash: "2 4" },
};
