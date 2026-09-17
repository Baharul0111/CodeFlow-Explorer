"use client";

import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath } from "@xyflow/react";
import type { EdgeProps } from "@xyflow/react";
import { memo } from "react";
import { EDGE_STYLE } from "./node-styles";

export interface FlowEdgeData extends Record<string, unknown> {
  label: string;
  shape: string;
  kind: string;
}

/**
 * An edge whose label is drawn in React Flow's label layer rather than on the SVG path.
 *
 * Labels painted onto the path sit underneath the node cards and get clipped mid-word; the label
 * renderer puts them in a DOM layer above everything, where they can have a solid background,
 * padding and a sensible maximum width.
 */
function FlowEdgeInner({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
}: EdgeProps) {
  const { label, shape, kind } = (data ?? {}) as FlowEdgeData;
  const style = EDGE_STYLE[kind ?? "data"] ?? EDGE_STYLE.data;
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 14,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{ stroke: style?.stroke, strokeDasharray: style?.dash, strokeWidth: 1.5 }}
      />
      {label ? (
        <EdgeLabelRenderer>
          <div
            data-testid="edge-label"
            className="nodrag nopan pointer-events-auto absolute max-w-[200px] truncate rounded-md border border-border bg-surface px-1.5 py-0.5 text-[11px] font-medium leading-tight text-muted shadow-[var(--shadow-sm)]"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
            title={shape ? `${label} — ${shape}` : label}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

export const FlowEdge = memo(FlowEdgeInner);
