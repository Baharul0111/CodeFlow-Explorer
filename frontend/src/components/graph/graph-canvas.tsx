"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import type { Edge, Node, NodeMouseHandler } from "@xyflow/react";
import { toPng } from "html-to-image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, subscribeToProgress } from "@/lib/api";
import {
  ancestorPath,
  collapseSubtree,
  expandPath,
  indexGraph,
  visibleGraph,
} from "@/lib/graph-state";
import { NODE_HEIGHT, NODE_WIDTH, layoutGraph } from "@/lib/layout";
import type { Graph, SearchHit } from "@/lib/schemas";
import { Alert, Button, Spinner } from "@/components/ui/primitives";
import { FlowNodeCard, GroupNodeCard } from "./flow-node";
import type { FlowNodeData } from "./flow-node";
import { Breadcrumbs, GraphToolbar, Legend, SearchBox } from "./graph-chrome";
import { EDGE_STYLE } from "./node-styles";
import { SidePanel } from "./side-panel";
import { useNodeColors } from "./use-theme-colors";

const NODE_TYPES = { step: FlowNodeCard, group: GroupNodeCard };

interface Props {
  projectId: string;
  projectName: string;
  initialGraph: Graph;
}

function GraphCanvasInner({ projectId, projectName, initialGraph }: Props) {
  const [graph, setGraph] = useState<Graph>(initialGraph);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [focusId, setFocusId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyNodes, setBusyNodes] = useState<Set<string>>(new Set());
  // React Flow owns node state so it can record its own measurements (the minimap and
  // fit-to-view both need them); our layout pass writes positions back into it.
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [error, setError] = useState<string | null>(null);
  const [laidOut, setLaidOut] = useState(false);
  // The node the view should settle on after the next layout (what the user just opened).
  const [fitTarget, setFitTarget] = useState<string | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const { fitView } = useReactFlow();
  const nodesInitialized = useNodesInitialized();
  const nodeColors = useNodeColors();

  const index = useMemo(() => indexGraph(graph.nodes, graph.edges), [graph]);

  const merge = useCallback((incoming: Graph) => {
    setGraph((current) => {
      const nodes = new Map(current.nodes.map((node) => [node.id, node]));
      for (const node of incoming.nodes) nodes.set(node.id, node);
      const edges = new Map(current.edges.map((edge) => [edge.id, edge]));
      for (const edge of incoming.edges) edges.set(edge.id, edge);
      return { ...current, nodes: [...nodes.values()], edges: [...edges.values()] };
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      merge(await api.getGraph(projectId));
    } catch {
      /* keep what is already on screen */
    }
  }, [projectId, merge]);

  // Background generation keeps adding levels; pull them in as they land.
  useEffect(() => {
    return subscribeToProgress(projectId, ({ type }) => {
      if (type === "nodes" || type === "done") void refresh();
    });
  }, [projectId, refresh]);

  const expandNode = useCallback(
    async (nodeId: string) => {
      const node = index.byId.get(nodeId);
      if (!node?.has_children) return;
      const alreadyLoaded = (index.childrenOf.get(nodeId) ?? []).length > 0;
      setFitTarget(nodeId);
      setExpanded((current) => {
        const next = new Set(current);
        next.add(nodeId);
        return next;
      });
      if (alreadyLoaded) return;
      setBusyNodes((current) => new Set(current).add(nodeId));
      setError(null);
      try {
        const result = await api.expandNode(projectId, nodeId);
        merge(result);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not open up this step.");
        setExpanded((current) => {
          const next = new Set(current);
          next.delete(nodeId);
          return next;
        });
      } finally {
        setBusyNodes((current) => {
          const next = new Set(current);
          next.delete(nodeId);
          return next;
        });
      }
    },
    [index, projectId, merge],
  );

  const toggle = useCallback(
    (nodeId: string) => {
      if (expanded.has(nodeId)) {
        setFitTarget(null);
        setExpanded(collapseSubtree(expanded, index, nodeId));
      } else {
        void expandNode(nodeId);
      }
    },
    [expanded, index, expandNode],
  );

  const focusOn = useCallback(
    (nodeId: string | null) => {
      setFitTarget(null);
      setFocusId(nodeId);
      setSelectedId(nodeId);
      if (nodeId) void expandNode(nodeId);
    },
    [expandNode],
  );

  const jumpTo = useCallback(
    async (hit: SearchHit) => {
      // Open every ancestor so the node is actually on screen, then select it.
      for (const ancestorId of hit.path.slice(0, -1)) {
        await expandNode(ancestorId);
      }
      setExpanded((current) => expandPath(current, index, hit.node_id));
      setSelectedId(hit.node_id);
    },
    [expandNode, index],
  );

  const visible = useMemo(() => visibleGraph(index, expanded, focusId), [index, expanded, focusId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const positions = await layoutGraph(visible.nodes, visible.edges, expanded, focusId);
      if (cancelled) return;
      const nodes: Node[] = visible.nodes
        .filter((node) => positions.has(node.id))
        .map((node) => {
          const position = positions.get(node.id);
          if (!position) throw new Error("missing position");
          const data: FlowNodeData = {
            node,
            expanded: expanded.has(node.id),
            selected: selectedId === node.id,
            busy: busyNodes.has(node.id),
            onToggle: toggle,
            onFocus: focusOn,
          };
          return {
            id: node.id,
            type: position.isContainer ? "group" : "step",
            position: { x: position.x, y: position.y },
            data: data as unknown as Record<string, unknown>,
            ...(position.parentId
              ? { parentId: position.parentId, extent: "parent" as const }
              : {}),
            style: {
              width: position.width || NODE_WIDTH,
              height: position.height || NODE_HEIGHT,
            },
            selectable: true,
            draggable: false,
            zIndex: position.isContainer ? 0 : 1,
          };
        });
      const edges: Edge[] = visible.edges.map((edge) => {
        const style = EDGE_STYLE[edge.kind] ?? EDGE_STYLE.data;
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: edge.label,
          labelShowBg: true,
          type: "smoothstep",
          animated: false,
          style: { stroke: style?.stroke, strokeDasharray: style?.dash, strokeWidth: 1.5 },
          markerEnd: { type: "arrowclosed", color: style?.stroke } as Edge["markerEnd"],
          data: { shape: edge.data_shape },
        };
      });
      setRfNodes(nodes);
      setRfEdges(edges);
      setLaidOut(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [visible, expanded, focusId, selectedId, busyNodes, toggle, focusOn]);

  // Fit only once React Flow has measured the nodes, otherwise it fits an empty box. After an
  // expansion the view settles on the node that was opened, so its children stay readable.
  useEffect(() => {
    if (!laidOut || !nodesInitialized || rfNodes.length === 0) return;
    const target = fitTarget && rfNodes.some((node) => node.id === fitTarget) ? fitTarget : null;
    const id = window.setTimeout(() => {
      void fitView(
        target
          ? { nodes: [{ id: target }], duration: 350, padding: 0.3, maxZoom: 1.1 }
          : { duration: 350, padding: 0.16, maxZoom: 1.1 },
      );
    }, 30);
    return () => window.clearTimeout(id);
  }, [laidOut, nodesInitialized, rfNodes, fitView, fitTarget]);

  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    setSelectedId(node.id);
  }, []);

  const exportPng = useCallback(async () => {
    const viewport = wrapper.current?.querySelector<HTMLElement>(".react-flow__viewport");
    if (!viewport) return;
    const background = getComputedStyle(document.body).backgroundColor;
    const dataUrl = await toPng(viewport, { backgroundColor: background, pixelRatio: 2 });
    const link = document.createElement("a");
    link.download = `${projectName || "codeflow"}-flow.png`;
    link.href = dataUrl;
    link.click();
  }, [projectName]);

  const selected = selectedId ? (index.byId.get(selectedId) ?? null) : null;
  const trail = focusId ? ancestorPath(index, focusId) : [];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <GraphToolbar projectId={projectId} projectName={projectName} onExportPng={exportPng}>
        <SearchBox projectId={projectId} onPick={(hit) => void jumpTo(hit)} />
      </GraphToolbar>

      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface px-4 py-1.5">
        <Breadcrumbs trail={trail} onJump={focusOn} />
        <div className="ml-auto">
          <Legend />
        </div>
      </div>

      {error ? (
        <div className="px-4 pt-2">
          <Alert tone="error">{error}</Alert>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div ref={wrapper} className="relative min-h-[420px] flex-1 bg-bg">
          {!laidOut ? (
            <div className="absolute inset-0 z-10 flex items-center justify-center gap-2 text-sm text-muted">
              <Spinner /> Laying out the flow…
            </div>
          ) : null}
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={NODE_TYPES}
            onNodeClick={onNodeClick}
            onPaneClick={() => setSelectedId(null)}
            proOptions={{ hideAttribution: true }}
            minZoom={0.1}
            maxZoom={2}
            fitView
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--border)" />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              style={{ width: 170, height: 110 }}
              nodeColor={(node) => {
                const data = node.data as unknown as FlowNodeData;
                return data.node ? nodeColors[data.node.kind] : "#888";
              }}
              nodeStrokeWidth={2}
              maskColor="rgb(0 0 0 / 0.35)"
            />
          </ReactFlow>
          {rfNodes.length === 0 && laidOut ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center">
              <p className="text-sm text-muted">Nothing to show here yet.</p>
              {focusId ? (
                <Button variant="secondary" onClick={() => focusOn(null)}>
                  Back to the whole system
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>

        <SidePanel
          projectId={projectId}
          node={selected}
          busy={selected ? busyNodes.has(selected.id) : false}
          onClose={() => setSelectedId(null)}
          onGoDeeper={(id) => void expandNode(id)}
        />
      </div>
    </div>
  );
}

export function GraphCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <GraphCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
