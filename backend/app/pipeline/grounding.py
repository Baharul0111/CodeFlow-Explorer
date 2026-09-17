"""Validate and repair Claude's flow JSON against the real code map.

Two kinds of problem:

* **Hard** — the answer refers to something that does not exist (an id that was not on the menu, a
  file that is not in the upload, lines outside the function). These are reported back for one
  repair call, and the node is never persisted ungrounded.
* **Soft** — style slips we can fix ourselves without another call: over-long titles, missing
  edges, a level-0 flow without a start or output node, duplicate keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.api.schemas import CodeRef
from app.llm.schemas import FlowResponse, LlmEdge, LlmNode
from app.parsing.codemap import CodeMap
from app.pipeline.units import Unit, is_file, is_module, is_symbol

MAX_TITLE_WORDS = 5
MAX_EXPLANATION_WORDS = 25
MAX_LABEL_WORDS = 6
MAX_IO_ITEMS = 4
MAX_DATA_SHAPE_CHARS = 60


@dataclass(slots=True)
class GroundedNode:
    key: str
    kind: str
    title: str
    explanation: str
    inputs: list[str]
    outputs: list[str]
    coverage: list[str]
    code_refs: list[CodeRef]


@dataclass(slots=True)
class GroundedFlow:
    nodes: list[GroundedNode] = field(default_factory=list)
    edges: list[LlmEdge] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.nodes)


def _words(text: str, limit: int) -> str:
    cleaned = " ".join(str(text).split())
    words = cleaned.split(" ")
    return " ".join(words[:limit]) if len(words) > limit else cleaned


def _code_refs_for_units(coverage: list[str], cm: CodeMap) -> list[CodeRef]:
    """Real file + line references for whatever a node covers.

    Empty files (``__init__.py`` and friends) are skipped unless they are all a node has, so the
    side panel never opens on a blank snippet.
    """
    refs: list[CodeRef] = []
    empty: list[CodeRef] = []
    for unit_id in coverage:
        if is_symbol(unit_id):
            sym = cm.symbols.get(unit_id)
            if sym is not None:
                refs.append(
                    CodeRef(
                        file=sym.file,
                        start_line=sym.start_line,
                        end_line=sym.end_line,
                        symbol=sym.qualname,
                    )
                )
        elif is_file(unit_id):
            path = unit_id.split(":", 1)[1]
            fm = cm.files.get(path)
            if fm is not None:
                ref = CodeRef(file=path, start_line=1, end_line=max(1, fm.lines), symbol="")
                (refs if fm.lines > 0 else empty).append(ref)
        elif is_module(unit_id):
            directory = unit_id.split(":", 1)[1]
            paths = sorted(p for p in cm.files if cm.module_of(p) == directory)
            for path in [p for p in paths if cm.files[p].lines > 0][:3] or paths[:1]:
                fm = cm.files[path]
                ref = CodeRef(file=path, start_line=1, end_line=max(1, fm.lines), symbol="")
                (refs if fm.lines > 0 else empty).append(ref)
    return (refs or empty)[:12]


def _clean_node(
    node: LlmNode, coverage: list[str], refs: list[CodeRef], fixes: list[str]
) -> GroundedNode:
    title = _words(node.title, MAX_TITLE_WORDS) or "Do the work"
    if title != " ".join(node.title.split()):
        fixes.append(f"shortened title for {node.key}")
    explanation = _words(node.explanation, MAX_EXPLANATION_WORDS)
    return GroundedNode(
        key=node.key,
        kind=node.kind,
        title=title,
        explanation=explanation,
        inputs=[_words(i, MAX_LABEL_WORDS) for i in node.inputs[:MAX_IO_ITEMS] if str(i).strip()],
        outputs=[_words(o, MAX_LABEL_WORDS) for o in node.outputs[:MAX_IO_ITEMS] if str(o).strip()],
        coverage=coverage,
        code_refs=refs,
    )


def _dedupe_keys(nodes: list[LlmNode], problems: list[str]) -> list[LlmNode]:
    seen: set[str] = set()
    out: list[LlmNode] = []
    for node in nodes:
        if node.key in seen:
            problems.append(f"Two nodes share the key '{node.key}'. Keys must be unique.")
            continue
        seen.add(node.key)
        out.append(node)
    return out


def _fix_edges(nodes: list[GroundedNode], edges: list[LlmEdge], fixes: list[str]) -> list[LlmEdge]:
    keys = {n.key for n in nodes}
    kept: list[LlmEdge] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        if edge.source not in keys or edge.target not in keys or edge.source == edge.target:
            fixes.append(f"dropped edge {edge.source}->{edge.target}")
            continue
        if (edge.source, edge.target) in seen:
            continue
        seen.add((edge.source, edge.target))
        kept.append(
            LlmEdge(
                source=edge.source,
                target=edge.target,
                label=_words(edge.label, MAX_LABEL_WORDS) or "information",
                data_shape=" ".join(str(edge.data_shape).split())[:MAX_DATA_SHAPE_CHARS],
                kind=edge.kind,
            )
        )
    if len(nodes) > 1 and not kept:
        fixes.append("added a straight chain because no usable edges were returned")
        kept = [
            LlmEdge(
                source=nodes[i].key,
                target=nodes[i + 1].key,
                label="information",
                data_shape="",
                kind="data",
            )
            for i in range(len(nodes) - 1)
        ]
    else:
        connected = {e.source for e in kept} | {e.target for e in kept}
        for index, node in enumerate(nodes):
            if node.key in connected:
                continue
            neighbour = nodes[index - 1] if index else (nodes[1] if len(nodes) > 1 else None)
            if neighbour is None:
                continue
            source, target = (neighbour.key, node.key) if index else (node.key, neighbour.key)
            kept.append(
                LlmEdge(
                    source=source, target=target, label="information", data_shape="", kind="data"
                )
            )
            fixes.append(f"connected {node.key} to the flow")
    return kept


def _ensure_start_and_output(nodes: list[GroundedNode], fixes: list[str]) -> None:
    if not nodes:
        return
    if not any(n.kind == "start" for n in nodes):
        nodes[0].kind = "start"
        fixes.append("marked the first node as the start")
    if not any(n.kind == "output" for n in nodes):
        nodes[-1].kind = "output"
        fixes.append("marked the last node as the output")


def validate_structural_flow(
    response: FlowResponse,
    *,
    menu: list[Unit],
    cm: CodeMap,
    require_start_and_output: bool = False,
) -> GroundedFlow:
    """Check a flow whose children cover *units* (system, stage, group, file levels)."""
    flow = GroundedFlow()
    allowed = {u.id for u in menu}
    if not response.nodes:
        flow.problems.append("No nodes were returned. Return between 2 and 8 nodes.")
        return flow
    nodes = _dedupe_keys(response.nodes, flow.problems)

    assigned: dict[str, str] = {}
    grounded: list[GroundedNode] = []
    for node in nodes:
        coverage: list[str] = []
        for unit_id in node.covers:
            if unit_id not in allowed:
                flow.problems.append(
                    f"Node '{node.key}' uses the id '{unit_id}', which was not in the list. "
                    "Use only the ids you were given."
                )
                continue
            if unit_id in assigned:
                flow.problems.append(
                    f"The id '{unit_id}' is used by both '{assigned[unit_id]}' and '{node.key}'. "
                    "Each id belongs to exactly one node."
                )
                continue
            assigned[unit_id] = node.key
            coverage.append(unit_id)
        grounded.append(_clean_node(node, coverage, _code_refs_for_units(coverage, cm), flow.fixes))

    missing = [u.id for u in menu if u.id not in assigned]
    if missing:
        shown = ", ".join(missing[:20])
        flow.problems.append(
            "These ids were left out and must each be added to exactly one node's "
            f"'covers': {shown}"
        )
    flow.nodes = grounded
    if require_start_and_output:
        _ensure_start_and_output(flow.nodes, flow.fixes)
    flow.edges = _fix_edges(flow.nodes, response.edges, flow.fixes)
    return flow


def validate_step_flow(
    response: FlowResponse, *, file: str, start_line: int, end_line: int, symbol: str, cm: CodeMap
) -> GroundedFlow:
    """Check steps inside one function: every step must sit on real lines of that function."""
    flow = GroundedFlow()
    if file not in cm.files:
        flow.problems.append(f"The file '{file}' is not part of this project.")
        return flow
    if not response.nodes:
        flow.problems.append("No steps were returned. Return between 2 and 8 steps.")
        return flow
    nodes = _dedupe_keys(response.nodes, flow.problems)
    grounded: list[GroundedNode] = []
    for node in nodes:
        first, last = node.start_line, node.end_line
        if first <= 0 or last <= 0:
            flow.problems.append(
                f"Step '{node.key}' has no line numbers. Set 'start_line' and 'end_line' to real "
                f"lines between {start_line} and {end_line}."
            )
            continue
        if first > last:
            first, last = last, first
            flow.fixes.append(f"swapped the line numbers of {node.key}")
        if first < start_line or last > end_line:
            flow.problems.append(
                f"Step '{node.key}' uses lines {first}-{last}, which are outside this function "
                f"(lines {start_line} to {end_line})."
            )
            continue
        refs = [CodeRef(file=file, start_line=first, end_line=last, symbol=symbol)]
        grounded.append(_clean_node(node, [], refs, flow.fixes))
    if not grounded and not flow.problems:
        flow.problems.append("No usable steps were returned.")
    flow.nodes = grounded
    flow.edges = _fix_edges(flow.nodes, response.edges, flow.fixes)
    return flow


def refs_exist(refs: list[CodeRef], cm: CodeMap) -> bool:
    """Final safety net before persisting: every reference points at real lines of a real file."""
    for ref in refs:
        fm = cm.files.get(ref.file)
        if fm is None:
            return False
        limit = max(fm.lines, 1)
        if ref.start_line < 1 or ref.end_line < ref.start_line or ref.start_line > limit:
            return False
    return True


def repair_payload(flow: GroundedFlow, menu: list[Unit]) -> dict[str, object]:
    """Only the problems (plus the id list) go back — never the whole context again."""
    return {
        "problems": flow.problems[:10],
        "ids": [u.id for u in menu],
    }
