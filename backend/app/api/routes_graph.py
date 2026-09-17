"""Graph endpoints: read the graph, expand a node on demand, search, snippets, export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, SettingsDep
from app.api.errors import AppError, NotFoundError
from app.api.model_resolution import models_for, resolve_api_key
from app.api.schemas import EdgeOut, NodeOut
from app.config import Settings
from app.export.viewer import ExportPayload, collect_snippets, render
from app.models.orm import FlowEdge, FlowNode, Project
from app.pipeline.analysis import AnalysisRequest, AnalysisService
from app.pipeline.projects import get_project, project_root

router = APIRouter(prefix="/api/projects/{project_id}/graph", tags=["graph"])

MAX_SNIPPET_LINES = 400
SNIPPET_CONTEXT = 2


class GraphResponse(BaseModel):
    nodes: list[NodeOut]
    edges: list[EdgeOut]
    status: str


class SnippetResponse(BaseModel):
    file: str
    start_line: int
    end_line: int
    language: str
    code: str


class SearchHit(BaseModel):
    node_id: str
    title: str
    subtitle: str
    path: list[str]


def _node_out(node: FlowNode) -> NodeOut:
    return NodeOut(
        id=node.id,
        parent_id=node.parent_id,
        level=node.level,
        kind=node.kind,
        title=node.title,
        explanation=node.explanation,
        inputs=[str(i) for i in node.inputs],
        outputs=[str(o) for o in node.outputs],
        code_refs=node.code_refs,
        has_children=node.has_children,
        status=node.status,
        scope=node.scope,
        error=node.error,
    )


def _edge_out(edge: FlowEdge) -> EdgeOut:
    return EdgeOut(
        id=edge.id,
        parent_id=edge.parent_id,
        source=edge.source,
        target=edge.target,
        label=edge.label,
        data_shape=edge.data_shape,
        kind=edge.kind,
    )


async def _all_nodes(session: AsyncSession, project_id: str) -> list[FlowNode]:
    stmt = (
        select(FlowNode)
        .where(FlowNode.project_id == project_id)
        .order_by(FlowNode.level, FlowNode.order_index)
    )
    return list((await session.execute(stmt)).scalars())


async def _all_edges(session: AsyncSession, project_id: str) -> list[FlowEdge]:
    stmt = select(FlowEdge).where(FlowEdge.project_id == project_id)
    return list((await session.execute(stmt)).scalars())


def _service(request: Request) -> AnalysisService:
    service: AnalysisService = request.app.state.analysis
    return service


def safe_workspace_path(settings: Settings, project: Project, relative: str) -> Path:
    """Resolve a file inside the project's workspace, refusing anything that escapes it."""
    root = project_root(settings, project).resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise AppError("That file is not part of this project.", code="bad_path", status_code=400)
    if candidate.is_symlink() or not candidate.is_file():
        raise NotFoundError("That file is not in the uploaded project.")
    return candidate


@router.get("", response_model=GraphResponse)
async def get_graph(project_id: str, session: SessionDep) -> GraphResponse:
    project = await get_project(session, project_id)
    nodes = await _all_nodes(session, project_id)
    edges = await _all_edges(session, project_id)
    return GraphResponse(
        nodes=[_node_out(n) for n in nodes],
        edges=[_edge_out(e) for e in edges],
        status=project.status,
    )


@router.get("/nodes/{node_id}/children", response_model=GraphResponse)
async def children(project_id: str, node_id: str, session: SessionDep) -> GraphResponse:
    project = await get_project(session, project_id)
    stmt = (
        select(FlowNode)
        .where(FlowNode.project_id == project_id, FlowNode.parent_id == node_id)
        .order_by(FlowNode.order_index)
    )
    nodes = list((await session.execute(stmt)).scalars())
    edge_stmt = select(FlowEdge).where(
        FlowEdge.project_id == project_id, FlowEdge.parent_id == node_id
    )
    edges = list((await session.execute(edge_stmt)).scalars())
    return GraphResponse(
        nodes=[_node_out(n) for n in nodes],
        edges=[_edge_out(e) for e in edges],
        status=project.status,
    )


@router.post("/nodes/{node_id}/expand", response_model=GraphResponse)
async def expand(
    project_id: str,
    node_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    x_session_token: str | None = Header(default=None),
) -> GraphResponse:
    """Generate a node's children right now. Already-built children are returned for free."""
    project = await get_project(session, project_id)
    node = await session.get(FlowNode, node_id)
    if node is None or node.project_id != project_id:
        raise NotFoundError("That step is not part of this project.")
    existing = await children(project_id, node_id, session)
    if existing.nodes:
        return existing
    if not node.has_children:
        return GraphResponse(nodes=[], edges=[], status=project.status)

    models = await models_for(request, session, x_session_token)
    api_key = await resolve_api_key(request, session, x_session_token)
    service = _service(request)
    created = await service.expand_on_demand(
        AnalysisRequest(
            project_id=project_id,
            api_key=api_key,
            model_id=project.model_id or models[0].id,
            deep_model_id=project.deep_model_id or models[-1].id,
            models=models,
            cost_limit_usd=project.cost_limit_usd or settings.max_cost_per_project_usd,
        ),
        node_id,
    )
    if not created:
        return GraphResponse(nodes=[], edges=[], status=project.status)
    return await children(project_id, node_id, session)


@router.get("/search", response_model=list[SearchHit])
async def search(
    project_id: str, session: SessionDep, q: str = Query(min_length=1, max_length=120)
) -> list[SearchHit]:
    await get_project(session, project_id)
    nodes = await _all_nodes(session, project_id)
    by_id = {n.id: n for n in nodes}
    needle = q.lower()
    hits: list[SearchHit] = []
    for node in nodes:
        refs = [r for r in node.code_refs if isinstance(r, dict)]
        files = " ".join(str(r.get("file", "")) for r in refs)
        symbols = " ".join(str(r.get("symbol", "")) for r in refs)
        haystack = f"{node.title} {node.explanation} {files} {symbols}".lower()
        if needle not in haystack:
            continue
        path: list[str] = []
        cursor: FlowNode | None = node
        while cursor is not None:
            path.insert(0, cursor.id)
            cursor = by_id.get(cursor.parent_id) if cursor.parent_id else None
        subtitle = str(refs[0].get("file", "")) if refs else node.scope
        hits.append(SearchHit(node_id=node.id, title=node.title, subtitle=subtitle, path=path))
        if len(hits) >= 50:
            break
    return hits


@router.get("/snippet", response_model=SnippetResponse)
async def snippet(
    project_id: str,
    session: SessionDep,
    settings: SettingsDep,
    file: str = Query(max_length=400),
    start_line: int = Query(ge=1),
    end_line: int = Query(ge=1),
) -> SnippetResponse:
    project = await get_project(session, project_id)
    path = safe_workspace_path(settings, project, file)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise NotFoundError("That file could not be read.") from exc
    first = max(1, start_line - SNIPPET_CONTEXT)
    last = min(len(lines), max(start_line, end_line) + SNIPPET_CONTEXT)
    if last - first > MAX_SNIPPET_LINES:
        last = first + MAX_SNIPPET_LINES
    return SnippetResponse(
        file=file,
        start_line=first,
        end_line=last,
        language=path.suffix.lstrip("."),
        code="\n".join(lines[first - 1 : last]),
    )


@router.get("/export.html")
async def export_page(project_id: str, session: SessionDep, settings: SettingsDep) -> Response:
    """One self-contained HTML file: the whole graph, its code snippets, and a viewer.

    It opens offline by double-clicking and can be shared with anyone — expanding, searching and
    the side panel all work without this server.
    """
    project = await get_project(session, project_id)
    nodes = await _all_nodes(session, project_id)
    edges = await _all_edges(session, project_id)
    if not nodes:
        raise NotFoundError("This project has no flow to share yet.")
    node_payloads = [_node_out(n).model_dump() for n in nodes]
    html = render(
        ExportPayload(
            project={"id": project.id, "name": project.name, "model": project.model_id},
            nodes=node_payloads,
            edges=[_edge_out(e).model_dump() for e in edges],
            snippets=collect_snippets(project_root(settings, project), node_payloads),
        )
    )
    filename = f"{project.name or 'codeflow'}-flow.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export")
async def export_graph(project_id: str, session: SessionDep) -> Response:
    project = await get_project(session, project_id)
    nodes = await _all_nodes(session, project_id)
    edges = await _all_edges(session, project_id)
    payload: dict[str, Any] = {
        "project": {"id": project.id, "name": project.name, "model": project.model_id},
        "nodes": [_node_out(n).model_dump() for n in nodes],
        "edges": [_edge_out(e).model_dump() for e in edges],
    }
    body = json.dumps(payload, indent=2)
    filename = f"{project.name or 'codeflow'}-graph.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
