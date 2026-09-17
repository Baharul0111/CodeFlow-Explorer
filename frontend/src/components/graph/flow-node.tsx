"use client";

import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { memo } from "react";
import type { GraphNode } from "@/lib/schemas";
import { Spinner } from "@/components/ui/primitives";
import { KIND_SHORT, KIND_STYLE } from "./node-styles";

export interface FlowNodeData extends Record<string, unknown> {
  node: GraphNode;
  expanded: boolean;
  selected: boolean;
  busy: boolean;
  onToggle: (id: string) => void;
  onFocus: (id: string) => void;
}

function FlowNodeInner({ data, id }: NodeProps) {
  const { node, expanded, selected, busy, onToggle, onFocus } = data as FlowNodeData;
  const style = KIND_STYLE[node.kind];
  const canExpand = node.has_children;

  return (
    <div
      className={`group relative flex h-full w-full flex-col justify-center gap-1 rounded-[10px] border-l-[3px] px-3 py-2 text-left shadow-[var(--shadow-sm)] transition-shadow ${
        selected ? "ring-2 ring-[var(--focus)] ring-offset-1 ring-offset-[var(--bg)]" : ""
      }`}
      style={{
        background: style.bg,
        borderLeftColor: style.border,
        border: `1px solid var(--border)`,
        borderLeft: `3px solid ${style.border}`,
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
        if (canExpand) onFocus(id);
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!size-1.5 !border-0 !bg-[var(--border-strong)]"
      />
      <div className="flex items-center justify-between gap-2">
        <span
          className="text-[10px] font-bold uppercase tracking-wider"
          style={{ color: style.text }}
        >
          {KIND_SHORT[node.kind]}
        </span>
        <span className="flex items-center gap-1">
          {busy ? <Spinner className="text-[var(--text-muted)]" /> : null}
          {node.status === "error" ? (
            <span
              title={node.error ?? "This part could not be read"}
              className="text-xs text-danger"
            >
              !
            </span>
          ) : null}
          {canExpand ? (
            <button
              type="button"
              aria-label={expanded ? `Collapse ${node.title}` : `Open up ${node.title}`}
              aria-expanded={expanded}
              onClick={(event) => {
                event.stopPropagation();
                onToggle(id);
              }}
              className="flex size-5 items-center justify-center rounded border border-border bg-surface text-xs font-bold text-muted hover:text-text"
            >
              {expanded ? "−" : "+"}
            </button>
          ) : null}
        </span>
      </div>
      <p className="line-clamp-2 font-display text-sm font-semibold leading-tight text-text">
        {node.title}
      </p>
      <p className="line-clamp-2 text-xs leading-snug text-muted">{node.explanation}</p>
      <Handle
        type="source"
        position={Position.Right}
        className="!size-1.5 !border-0 !bg-[var(--border-strong)]"
      />
    </div>
  );
}

export const FlowNodeCard = memo(FlowNodeInner);

function GroupNodeInner({ data, id }: NodeProps) {
  const { node, onToggle, selected } = data as FlowNodeData;
  const style = KIND_STYLE[node.kind];
  return (
    <div
      className={`h-full w-full rounded-xl border border-dashed ${selected ? "ring-2 ring-[var(--focus)]" : ""}`}
      style={{
        borderColor: style.border,
        background: "color-mix(in srgb, var(--surface) 70%, transparent)",
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!size-1.5 !border-0 !bg-[var(--border-strong)]"
      />
      <div className="flex items-center gap-2 px-3 pt-2">
        <span
          className="text-[10px] font-bold uppercase tracking-wider"
          style={{ color: style.text }}
        >
          {KIND_SHORT[node.kind]}
        </span>
        <p className="truncate font-display text-sm font-semibold text-text">{node.title}</p>
        <button
          type="button"
          aria-label={`Collapse ${node.title}`}
          aria-expanded={true}
          onClick={(event) => {
            event.stopPropagation();
            onToggle(id);
          }}
          className="ml-auto flex size-5 items-center justify-center rounded border border-border bg-surface text-xs font-bold text-muted hover:text-text"
        >
          −
        </button>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!size-1.5 !border-0 !bg-[var(--border-strong)]"
      />
    </div>
  );
}

export const GroupNodeCard = memo(GroupNodeInner);
