"""Analysis endpoints: estimate, start, cancel, and the live progress stream."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.api.deps import ClientKeyDep, LimiterDep, SessionDep, SettingsDep
from app.api.errors import AppError, ConflictError
from app.api.model_resolution import models_for, resolve_api_key
from app.llm.catalog import find, pick_deep_model
from app.llm.factory import make_client
from app.llm.types import ModelSpec
from app.pipeline.analysis import AnalysisRequest, AnalysisService, build_project_block, channel_for
from app.pipeline.estimate import estimate_project
from app.pipeline.projects import get_project
from app.pipeline.scan import ScanResult

router = APIRouter(prefix="/api/projects/{project_id}/analysis", tags=["analysis"])


class AnalysisOptions(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    smart_mix: bool = True
    deep_model_id: str | None = None
    cost_limit_usd: float | None = Field(default=None, ge=0, le=1000)


class StartResponse(BaseModel):
    started: bool
    status: str
    model_id: str
    deep_model_id: str


def _service(request: Request) -> AnalysisService:
    service: AnalysisService = request.app.state.analysis
    return service


def _pick_models(models: list[ModelSpec], options: AnalysisOptions) -> tuple[str, str]:
    chosen = find(models, options.model_id)
    if chosen is None:
        raise AppError(
            "This model isn't available for your key. Pick a different model.",
            code="model_unavailable",
            status_code=404,
        )
    if not options.smart_mix:
        return chosen.id, chosen.id
    deep = options.deep_model_id or pick_deep_model(models, chosen.id)
    if find(models, deep) is None:
        deep = chosen.id
    return chosen.id, deep


@router.post("/estimate")
async def estimate(
    project_id: str,
    options: AnalysisOptions,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    key: ClientKeyDep,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    limiter.check(f"estimate:{key}", settings.rate_limit_analysis_per_minute)
    project = await get_project(session, project_id)
    service = _service(request)
    models = await models_for(request, session, x_session_token)
    top_model, deep_model = _pick_models(models, options)
    api_key = await resolve_api_key(request, session, x_session_token)

    scan = ScanResult.model_validate(project.scan or {})
    cm, _scan, _summaries, root = await service.prepare(session, project)
    block = build_project_block(project, scan, cm)

    client = make_client(settings, api_key)
    try:
        result = await estimate_project(
            client=client,
            cm=cm,
            root=root,
            project_block=block,
            top_model=top_model,
            deep_model=deep_model,
            top_spec=find(models, top_model),
            deep_spec=find(models, deep_model),
            limit_usd=options.cost_limit_usd
            if options.cost_limit_usd is not None
            else settings.max_cost_per_project_usd,
        )
    finally:
        await client.aclose()
    project.estimate = result.as_dict()
    project.model_id = top_model
    project.deep_model_id = deep_model
    await session.commit()
    return {"estimate": result.as_dict(), "scan": {"function_count": cm.stats()["functions"]}}


@router.post("/start", response_model=StartResponse)
async def start(
    project_id: str,
    options: AnalysisOptions,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    key: ClientKeyDep,
    x_session_token: str | None = Header(default=None),
) -> StartResponse:
    limiter.check(f"start:{key}", settings.rate_limit_analysis_per_minute)
    project = await get_project(session, project_id)
    if project.status == "analysing":
        raise ConflictError("This project is already being analysed.")
    models = await models_for(request, session, x_session_token)
    top_model, deep_model = _pick_models(models, options)
    api_key = await resolve_api_key(request, session, x_session_token)
    limit = (
        options.cost_limit_usd
        if options.cost_limit_usd is not None
        else settings.max_cost_per_project_usd
    )
    project.model_id = top_model
    project.deep_model_id = deep_model
    project.cost_limit_usd = limit
    project.status = "queued"
    await session.commit()
    started = _service(request).submit_analysis(
        AnalysisRequest(
            project_id=project_id,
            api_key=api_key,
            model_id=top_model,
            deep_model_id=deep_model,
            models=models,
            cost_limit_usd=limit,
        )
    )
    return StartResponse(
        started=started, status=project.status, model_id=top_model, deep_model_id=deep_model
    )


@router.post("/cancel", status_code=204)
async def cancel(project_id: str, request: Request, session: SessionDep) -> Response:
    project = await get_project(session, project_id)
    _service(request).cancel(project_id)
    project.status = "cancelled"
    await session.commit()
    return Response(status_code=204)


@router.get("/events")
async def events(
    project_id: str,
    request: Request,
    session: SessionDep,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    await get_project(session, project_id)
    bus = request.app.state.event_bus
    since = int(last_event_id) if last_event_id and last_event_id.isdigit() else None

    async def stream() -> Any:
        async for event in bus.subscribe(channel_for(project_id), last_event_id=since):
            if await request.is_disconnected():
                break
            yield event.sse()

    return EventSourceResponse(stream(), ping=15)


@router.get("/usage")
async def usage(project_id: str, request: Request, session: SessionDep) -> dict[str, Any]:
    await get_project(session, project_id)
    return await _service(request).totals(session, project_id)
