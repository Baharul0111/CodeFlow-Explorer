import ELK from "elkjs/lib/elk.bundled.js";
import type { ElkExtendedEdge, ElkNode } from "elkjs/lib/elk-api";
import type { GraphEdge, GraphNode } from "./schemas";

const elk = new ELK();

export const NODE_WIDTH = 264;
export const NODE_HEIGHT = 112;
const CONTAINER_HEADER = 46;
const CONTAINER_PADDING = 22;

// Rough character budgets for one line at the card's width, used to size a card to its text so
// nothing is ever cut off. Deliberately conservative: a little slack is better than a clipped word.
const TITLE_CHARS_PER_LINE = 26;
const BODY_CHARS_PER_LINE = 34;
const TITLE_LINE_HEIGHT = 19;
const BODY_LINE_HEIGHT = 17;
const CARD_CHROME = 38; // kind row, paddings and the gaps between the three blocks
const MAX_BODY_LINES = 6;

function lineCount(text: string, perLine: number, max = 99): number {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return 1;
  let lines = 1;
  let used = 0;
  for (const word of words) {
    const needed = used === 0 ? word.length : used + 1 + word.length;
    if (needed > perLine) {
      lines += 1;
      used = word.length;
    } else {
      used = needed;
    }
  }
  return Math.min(Math.max(lines, 1), max);
}

/** How tall a card must be to show its title and explanation in full. */
export function nodeHeight(node: Pick<GraphNode, "title" | "explanation">): number {
  const titleLines = lineCount(node.title, TITLE_CHARS_PER_LINE, 3);
  const bodyLines = lineCount(node.explanation, BODY_CHARS_PER_LINE, MAX_BODY_LINES);
  return Math.max(
    NODE_HEIGHT,
    CARD_CHROME + titleLines * TITLE_LINE_HEIGHT + bodyLines * BODY_LINE_HEIGHT,
  );
}

// Generous horizontal gaps: every edge carries a label that needs somewhere to sit.
const SPACING_OPTIONS: Record<string, string> = {
  "elk.layered.spacing.nodeNodeBetweenLayers": "170",
  "elk.spacing.nodeNode": "58",
  "elk.spacing.edgeNode": "36",
  "elk.spacing.edgeEdge": "22",
  "elk.layered.spacing.edgeNodeBetweenLayers": "40",
  "elk.layered.spacing.edgeEdgeBetweenLayers": "24",
};

const LAYOUT_OPTIONS: Record<string, string> = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  ...SPACING_OPTIONS,
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
        return { id: node.id, width: NODE_WIDTH, height: nodeHeight(node) };
      }
      return {
        id: node.id,
        children,
        layoutOptions: {
          // Spacing has to be repeated per container: ELK applies these to the graph they are set
          // on, so without them children were packed tight and edge labels landed on the cards.
          ...SPACING_OPTIONS,
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
