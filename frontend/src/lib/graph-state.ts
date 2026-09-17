import type { GraphEdge, GraphNode } from "./schemas";

export interface GraphIndex {
  byId: Map<string, GraphNode>;
  childrenOf: Map<string | null, GraphNode[]>;
  edgesOf: Map<string | null, GraphEdge[]>;
}

export function indexGraph(nodes: GraphNode[], edges: GraphEdge[]): GraphIndex {
  const byId = new Map<string, GraphNode>();
  const childrenOf = new Map<string | null, GraphNode[]>();
  const edgesOf = new Map<string | null, GraphEdge[]>();
  for (const node of nodes) {
    byId.set(node.id, node);
    const bucket = childrenOf.get(node.parent_id) ?? [];
    bucket.push(node);
    childrenOf.set(node.parent_id, bucket);
  }
  for (const edge of edges) {
    const bucket = edgesOf.get(edge.parent_id) ?? [];
    bucket.push(edge);
    edgesOf.set(edge.parent_id, bucket);
  }
  return { byId, childrenOf, edgesOf };
}

/** The chain of ancestors from the root down to (and including) `nodeId`. */
export function ancestorPath(index: GraphIndex, nodeId: string): GraphNode[] {
  const path: GraphNode[] = [];
  let current = index.byId.get(nodeId);
  while (current) {
    path.unshift(current);
    current = current.parent_id ? index.byId.get(current.parent_id) : undefined;
  }
  return path;
}

/**
 * Which nodes and edges are on screen, given what is expanded and which node (if any) is focused.
 * An expanded node shows its children nested inside it; a focused node becomes the temporary root.
 */
export function visibleGraph(
  index: GraphIndex,
  expanded: Set<string>,
  focusId: string | null,
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const rootParent = focusId ?? null;
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  const walk = (parentId: string | null): void => {
    const children = index.childrenOf.get(parentId) ?? [];
    if (children.length === 0) return;
    nodes.push(...children);
    edges.push(...(index.edgesOf.get(parentId) ?? []));
    for (const child of children) {
      if (expanded.has(child.id)) walk(child.id);
    }
  };

  walk(rootParent);
  return { nodes, edges };
}

/** Expanding a node also expands everything above it, so the path stays visible. */
export function expandPath(expanded: Set<string>, index: GraphIndex, nodeId: string): Set<string> {
  const next = new Set(expanded);
  for (const node of ancestorPath(index, nodeId)) {
    if (node.id !== nodeId) next.add(node.id);
  }
  return next;
}

export function collapseSubtree(
  expanded: Set<string>,
  index: GraphIndex,
  nodeId: string,
): Set<string> {
  const next = new Set(expanded);
  const stack = [nodeId];
  while (stack.length) {
    const current = stack.pop();
    if (current === undefined) continue;
    next.delete(current);
    for (const child of index.childrenOf.get(current) ?? []) stack.push(child.id);
  }
  return next;
}
