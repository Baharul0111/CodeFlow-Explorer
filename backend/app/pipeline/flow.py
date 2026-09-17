"""Hierarchical flow generation: level 0 (the whole system) and expanding any node.

Every generation step is: build a menu of real units → ask Claude with that menu → validate the
answer against the code map → repair at most twice → persist. Results are cached by content hash,
so reopening a project or re-uploading the same code costs nothing.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.cache import ResponseCache, cache_key
from app.llm.client import ClaudeClient, llm_errors
from app.llm.errors import BadOutputError, LlmError
from app.llm.prompts import (
    EXPAND_INSTRUCTION,
    PROMPT_VERSION,
    REPAIR_INSTRUCTION,
    STEPS_INSTRUCTION,
    SYSTEM_FLOW_INSTRUCTION,
    global_block,
    render_user_text,
)
from app.llm.schemas import FLOW_SCHEMA, FlowResponse
from app.llm.types import LlmResult, SystemBlock, Task
from app.logging_setup import get_logger
from app.models.orm import FlowEdge, FlowNode
from app.parsing.codemap import CodeMap, Symbol
from app.pipeline.grounding import (
    GroundedFlow,
    refs_exist,
    repair_payload,
    validate_step_flow,
    validate_structural_flow,
)
from app.pipeline.summaries import read_symbol_code
from app.pipeline.units import (
    Scope,
    Unit,
    child_menu,
    covered_files,
    expandable,
    is_symbol,
    top_level_units,
)

log = get_logger(__name__)

MAX_REPAIRS = 2
FLOW_MAX_TOKENS = 4_000
STEPS_MAX_TOKENS = 3_000
REPAIR_MAX_TOKENS = 4_000
MAX_CALLEE_SIGNATURES = 12

UsageHook = Callable[[Task, LlmResult, bool], Awaitable[None]]


def new_node_id() -> str:
    return secrets.token_hex(6)


@dataclass(slots=True)
class GenerationResult:
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    problems: list[str]
    fixes: list[str]


class FlowGenerator:
    """Generates one level of the graph at a time."""

    def __init__(
        self,
        *,
        client: ClaudeClient,
        cache: ResponseCache | None,
        project_id: str,
        project_block: SystemBlock,
        codemap: CodeMap,
        summaries: dict[str, str],
        root: Path,
        top_model: str,
        deep_model: str,
        on_usage: UsageHook | None = None,
        top_effort: str | None = None,
        deep_effort: str | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._project_id = project_id
        self._system = [global_block(), project_block]
        self._cm = codemap
        self._summaries = summaries
        self._root = root
        self._top_model = top_model
        self._deep_model = deep_model
        self._on_usage = on_usage
        self._top_effort = top_effort
        self._deep_effort = deep_effort

    def _model_for(self, scope: Scope) -> tuple[str, str | None]:
        if scope in ("step", "function"):
            return self._deep_model, self._deep_effort
        return self._top_model, self._top_effort

    async def _ask(
        self,
        task: Task,
        *,
        instruction: str,
        payload: dict[str, object],
        model: str,
        max_tokens: int,
        effort: str | None,
    ) -> FlowResponse:
        key = cache_key(task=task, model=model, prompt_version=PROMPT_VERSION, payload=payload)
        if self._cache is not None:
            hit = await self._cache.get(key)
            if hit is not None:
                if self._on_usage:
                    await self._on_usage(task, LlmResult(data=hit, model=model, cached=True), True)
                return FlowResponse.model_validate(hit)
        with llm_errors():
            result = await self._client.generate_json(
                task=task,
                system=self._system,
                user_text=render_user_text(task, instruction, payload),
                schema=FLOW_SCHEMA,
                model=model,
                max_tokens=max_tokens,
                effort=effort,
            )
        if self._cache is not None:
            await self._cache.put(key, task=task, model=model, response=result.data)
        if self._on_usage:
            await self._on_usage(task, result, False)
        return FlowResponse.model_validate(result.data)

    async def _ask_with_repair(
        self,
        *,
        task: Task,
        instruction: str,
        payload: dict[str, object],
        model: str,
        max_tokens: int,
        effort: str | None,
        validate: Callable[[FlowResponse], GroundedFlow],
        menu: list[Unit],
    ) -> GroundedFlow:
        response = await self._ask(
            task,
            instruction=instruction,
            payload=payload,
            model=model,
            max_tokens=max_tokens,
            effort=effort,
        )
        flow = validate(response)
        attempts = 0
        while not flow.ok and attempts < MAX_REPAIRS:
            attempts += 1
            log.info("flow_repair", task=task, attempt=attempts, problems=len(flow.problems))
            repair = dict(payload)
            repair["fix"] = repair_payload(flow, menu)
            response = await self._ask(
                "repair",
                instruction=REPAIR_INSTRUCTION,
                payload=repair,
                model=model,
                max_tokens=REPAIR_MAX_TOKENS,
                effort=effort,
            )
            flow = validate(response)
        if not flow.nodes:
            raise BadOutputError(
                "Claude could not describe this part of the code in the required format."
            )
        return flow

    # ----------------------------------------------------------------- levels
    async def generate_system_flow(self) -> GenerationResult:
        menu, child_scope = top_level_units(self._cm, self._summaries)
        entry_points = [
            f"{e.kind}: {e.file}:{e.line} {e.detail}".strip() for e in self._cm.entry_points[:20]
        ]
        payload: dict[str, object] = {
            "units": [u.as_payload() for u in menu],
            "entry_points": entry_points,
            "counts": self._cm.stats(),
        }
        model, effort = self._model_for("system")
        flow = await self._ask_with_repair(
            task="system_flow",
            instruction=SYSTEM_FLOW_INSTRUCTION,
            payload=payload,
            model=model,
            max_tokens=FLOW_MAX_TOKENS,
            effort=effort,
            validate=lambda r: validate_structural_flow(
                r, menu=menu, cm=self._cm, require_start_and_output=True
            ),
            menu=menu,
        )
        return self._materialise(flow, parent=None, level=0, child_scope=child_scope)

    async def expand_node(self, node: FlowNode) -> GenerationResult:
        coverage = [str(c) for c in node.coverage]
        if node.scope == "function" and len(coverage) == 1 and is_symbol(coverage[0]):
            sym = self._cm.symbols.get(coverage[0])
            if sym is not None and sym.kind != "class":
                return await self._expand_function(node, sym)
        menu, child_scope = child_menu(coverage, self._cm, self._summaries)
        if not menu:
            return GenerationResult(nodes=[], edges=[], problems=[], fixes=[])
        payload: dict[str, object] = {
            "parent": {
                "title": node.title,
                "explanation": node.explanation,
                "inputs": list(node.inputs),
                "outputs": list(node.outputs),
            },
            "units": [u.as_payload() for u in menu],
        }
        model, effort = self._model_for(child_scope)
        flow = await self._ask_with_repair(
            task="expand",
            instruction=EXPAND_INSTRUCTION,
            payload=payload,
            model=model,
            max_tokens=FLOW_MAX_TOKENS,
            effort=effort,
            validate=lambda r: validate_structural_flow(r, menu=menu, cm=self._cm),
            menu=menu,
        )
        return self._materialise(flow, parent=node, level=node.level + 1, child_scope=child_scope)

    async def _expand_function(self, node: FlowNode, sym: Symbol) -> GenerationResult:
        code = read_symbol_code(self._root, sym)
        if not code:
            return GenerationResult(
                nodes=[], edges=[], problems=["The source file is unreadable."], fixes=[]
            )
        callees = []
        for call in sym.project_calls[:MAX_CALLEE_SIGNATURES]:
            target = self._cm.symbols.get(call.resolved or "")
            if target is not None:
                callees.append(
                    {
                        "name": target.qualname,
                        "sig": f"{target.name}{target.params}",
                        "s": self._summaries.get(target.id, ""),
                    }
                )
        callers = [c.qualname for c in self._cm.callers_of(sym.id)[:5]]
        payload: dict[str, object] = {
            "function": {
                "id": sym.id,
                "name": sym.qualname,
                "file": sym.file,
                "start_line": sym.start_line,
                "end_line": sym.end_line,
                "lines": [
                    [sym.start_line + i, line.split(": ", 1)[-1]]
                    for i, line in enumerate(code.splitlines())
                ],
            },
            "calls": callees,
            "called_by": callers,
        }
        model, effort = self._model_for("step")
        flow = await self._ask_with_repair(
            task="steps",
            instruction=STEPS_INSTRUCTION,
            payload=payload,
            model=model,
            max_tokens=STEPS_MAX_TOKENS,
            effort=effort,
            validate=lambda r: validate_step_flow(
                r,
                file=sym.file,
                start_line=sym.start_line,
                end_line=sym.end_line,
                symbol=sym.qualname,
                cm=self._cm,
            ),
            menu=[],
        )
        return self._materialise(
            flow, parent=node, level=node.level + 1, child_scope="step", callee_of=sym
        )

    # ------------------------------------------------------------ persistence
    def _materialise(
        self,
        flow: GroundedFlow,
        *,
        parent: FlowNode | None,
        level: int,
        child_scope: Scope,
        callee_of: Symbol | None = None,
    ) -> GenerationResult:
        parent_id = parent.id if parent is not None else None
        key_to_id: dict[str, str] = {}
        nodes: list[FlowNode] = []
        for index, grounded in enumerate(flow.nodes):
            if not refs_exist(grounded.code_refs, self._cm):
                flow.problems.append(
                    f"Dropped '{grounded.title}': it pointed at code that is not here."
                )
                continue
            node_id = new_node_id()
            key_to_id[grounded.key] = node_id
            scope = child_scope
            if child_scope == "function" and len(grounded.coverage) == 1:
                sym = self._cm.symbols.get(grounded.coverage[0])
                if sym is not None and sym.kind == "class":
                    scope = "file"
            has_children = (
                False if child_scope == "step" else expandable(grounded.coverage, self._cm, scope)
            )
            nodes.append(
                FlowNode(
                    id=node_id,
                    project_id=self._project_id,
                    parent_id=parent_id,
                    level=level,
                    order_index=index,
                    kind=grounded.kind,
                    title=grounded.title,
                    explanation=grounded.explanation,
                    inputs=grounded.inputs,
                    outputs=grounded.outputs,
                    code_refs=[r.model_dump() for r in grounded.code_refs],
                    coverage=grounded.coverage,
                    scope=scope,
                    has_children=has_children,
                    status="ready",
                )
            )
        edges = [
            FlowEdge(
                id=new_node_id(),
                project_id=self._project_id,
                parent_id=parent_id,
                source=key_to_id[edge.source],
                target=key_to_id[edge.target],
                label=edge.label,
                data_shape=edge.data_shape,
                kind=edge.kind,
            )
            for edge in flow.edges
            if edge.source in key_to_id and edge.target in key_to_id
        ]
        if callee_of is not None:
            _link_steps_to_callees(nodes, callee_of, self._cm)
        return GenerationResult(nodes=nodes, edges=edges, problems=flow.problems, fixes=flow.fixes)


def _link_steps_to_callees(nodes: list[FlowNode], sym: Symbol, cm: CodeMap) -> None:
    """A step that calls another project function can be drilled into further."""
    for node in nodes:
        refs = [r for r in node.code_refs if isinstance(r, dict)]
        if not refs:
            continue
        start = int(refs[0].get("start_line", 0))
        end = int(refs[0].get("end_line", 0))
        targets = [
            c.resolved
            for c in sym.project_calls
            if c.resolved and start <= c.line <= end and c.resolved != sym.id
        ]
        if targets:
            node.coverage = [targets[0]]
            node.scope = "function"
            node.has_children = True
            target = cm.symbols.get(targets[0])
            if target is not None:
                node.code_refs = [
                    *refs,
                    {
                        "file": target.file,
                        "start_line": target.start_line,
                        "end_line": target.end_line,
                        "symbol": target.qualname,
                    },
                ]


async def persist(session: AsyncSession, result: GenerationResult) -> None:
    for node in result.nodes:
        session.add(node)
    for edge in result.edges:
        session.add(edge)
    await session.commit()


async def load_children(
    session: AsyncSession, project_id: str, parent_id: str | None
) -> list[FlowNode]:
    stmt = (
        select(FlowNode)
        .where(FlowNode.project_id == project_id, FlowNode.parent_id.is_(parent_id))
        .order_by(FlowNode.order_index)
    )
    return list((await session.execute(stmt)).scalars())


def covered_file_count(node: FlowNode, cm: CodeMap) -> int:
    return len(covered_files([str(c) for c in node.coverage], cm))


__all__ = [
    "FlowGenerator",
    "GenerationResult",
    "LlmError",
    "covered_file_count",
    "load_children",
    "new_node_id",
    "persist",
]
