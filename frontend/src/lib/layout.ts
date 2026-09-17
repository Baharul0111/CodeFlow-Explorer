import ELK from "elkjs/lib/elk.bundled.js";
import type { ElkExtendedEdge, ElkNode } from "elkjs/lib/elk-api";
import type { GraphEdge, GraphNode } from "./schemas";

const elk = new ELK();

export const NODE_WIDTH = 236;
export const NODE_HEIGHT = 108;
const CONTAINER_HEADER = 44;
const CONTAINER_PADDING = 20;

const LAYOUT_OPTIONS: Record<string, string> = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  "elk.layered.spacing.nodeNodeBetweenLayers": "88",
  "elk.spacing.nodeNode": "44",
  "elk.spacing.edgeNode": "28",
  "elk.layered.spacing.edgeNodeBetweenLayers": "32",
  "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
  "elk.layered.crossingMinimization.semiInteractive": "true",
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
  "elk.edgeRouting": "POLYLINE",
};

export interface PositionedNode {
  id: string;
  parentId: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  isContainer: boolean;
}

/**
 * Lay the visible graph out left to right with ELK. Expanded nodes become containers whose
 * children are positioned relative to them, which is exactly what React Flow's `parentId` wants.
 */
export async function layoutGraph(
  nodes: GraphNode[],
  edges: GraphEdge[],
  expanded: Set<string>,
  rootParent: string | null,
): Promise<Map<string, PositionedNode>> {
  const byParent = new Map<string | null, GraphNode[]>();
  for (const node of nodes) {
    const bucket = byParent.get(node.parent_id) ?? [];
    bucket.push(node);
    byParent.set(node.parent_id, bucket);
  }

  const build = (parentId: string | null): ElkNode[] =>
    (byParent.get(parentId) ?? []).map((node) => {
      const children = expanded.has(node.id) ? build(node.id) : [];
      if (children.length === 0) {
        return { id: node.id, width: NODE_WIDTH, height: NODE_HEIGHT };
      }
      return {
        id: node.id,
        children,
        layoutOptions: {
          "elk.padding": `[top=${CONTAINER_HEADER},left=${CONTAINER_PADDING},bottom=${CONTAINER_PADDING},right=${CONTAINER_PADDING}]`,
          "elk.direction": "RIGHT",
        },
      };
    });

  const elkEdges: ElkExtendedEdge[] = edges.map((edge) => ({
    id: edge.id,
    sources: [edge.source],
    targets: [edge.target],
  }));

  const graph: ElkNode = {
    id: "root",
    layoutOptions: LAYOUT_OPTIONS,
    children: build(rootParent),
    edges: elkEdges,
  };

  const laid = await elk.layout(graph);
  const positions = new Map<string, PositionedNode>();

  const collect = (parent: ElkNode, parentId: string | null): void => {
    for (const child of parent.children ?? []) {
      positions.set(child.id, {
        id: child.id,
        parentId,
        x: child.x ?? 0,
        y: child.y ?? 0,
        width: child.width ?? NODE_WIDTH,
        height: child.height ?? NODE_HEIGHT,
        isContainer: (child.children?.length ?? 0) > 0,
      });
      collect(child, child.id);
    }
  };

  collect(laid, null);
  return positions;
}
