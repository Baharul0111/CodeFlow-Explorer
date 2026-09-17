"""Orchestration: run the pipeline for one project and stream progress.

Stages: Unzipping and Scanning happen at upload time; this module runs Parsing → Building
summaries → Building the top flow → Building deeper levels. The top flow is published as soon as
it is ready so the user can open the graph while deeper levels keep generating in the background.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.llm.cache import ResponseCache
from app.llm.catalog import find
from app.llm.client import ClaudeClient
from app.llm.errors import CostLimitError, LlmError
from app.llm.factory import make_client
from app.llm.prompts import project_block
from app.llm.types import LlmResult, ModelSpec, SystemBlock, Task
from app.logging_setup import get_logger
from app.models.orm import FlowEdge, FlowNode, Project, UsageEvent
from app.parsing.builder import build_codemap, load_codemap, save_codemap
from app.parsing.codemap import CodeMap
from app.pipeline.cost import cost_usd
from app.pipeline.events import EventBus
from app.pipeline.flow import FlowGenerator, load_children, persist
from app.pipeline.jobs import PRIORITY_BACKGROUND, PRIORITY_INTERACTIVE, JobRunner
from app.pipeline.projects import project_dir, project_root
from app.pipeline.scan import ScanResult
from app.pipeline.summaries import SummaryGenerator, load_summaries, save_summaries

log = get_logger(__name__)

STAGES = ("parsing", "summaries", "top_flow", "deeper_levels")
STAGE_WEIGHTS = {"parsing": 0.1, "summaries": 0.5, "top_flow": 0.15, "deeper_levels": 0.25}
STAGE_LABELS = {
    "parsing": "Parsing",
    "summaries": "Building summaries",
    "top_flow": "Building top flow",
    "deeper_levels": "Building deeper levels",
}


def channel_for(project_id: str) -> str:
    return f"project:{project_id}"


def job_key(project_id: str, suffix: str = "") -> str:
    return f"analysis:{project_id}{suffix}"


UsageHook = Callable[[Task, LlmResult, bool], Awaitable[None]]


@dataclass(slots=True)
class AnalysisRequest:
    project_id: str
    api_key: str | None
    model_id: str
    deep_model_id: str
    models: list[ModelSpec]
    cost_limit_usd: float


@dataclass(slots=True)
class RunContext:
    """Everything one analysis run needs, assembled once and passed around."""

    request: AnalysisRequest
    block: SystemBlock
    codemap: CodeMap
    summaries: dict[str, str]
    root: Path
    usage: UsageHook

    @property
    def project_id(self) -> str:
        return self.request.project_id


def build_project_block(project: Project, scan: ScanResult, cm: CodeMap | None) -> SystemBlock:
    entry_points = []
    if cm is not None:
        entry_points = [f"{e.kind}: {e.file}:{e.line} {e.detail}".strip() for e in cm.entry_points]
    else:
        entry_points = [f"{h.kind}: {h.file} {h.detail}".strip() for h in scan.entry_hints]
    return project_block(
        name=project.name,
        languages={k: v.files for k, v in scan.languages.items()},
        frameworks=scan.frameworks,
        readme=scan.readme_excerpt,
        tree=scan.tree,
        entry_points=entry_points,
    )


class AnalysisService:
    """Owns the job runner and the event bus, and knows how to analyse one project."""

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        runner: JobRunner,
        bus: EventBus,
    ) -> None:
        self._settings = settings
        self._sessions = session_factory
        self._runner = runner
        self._bus = bus

    # ------------------------------------------------------------------ utils
    def publish(
        self, project_id: str, event: str, data: Mapping[str, object] | None = None
    ) -> None:
        self._bus.publish(channel_for(project_id), event, dict(data or {}))

    async def totals(self, session: AsyncSession, project_id: str) -> dict[str, float]:
        stmt = select(
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cache_write_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cache_read_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
            func.count(UsageEvent.id),
        ).where(UsageEvent.project_id == project_id)
        row = (await session.execute(stmt)).one()
        return {
            "input_tokens": int(row[0]),
            "output_tokens": int(row[1]),
            "cache_write_tokens": int(row[2]),
            "cache_read_tokens": int(row[3]),
            "cost_usd": round(float(row[4]), 6),
            "calls": int(row[5]),
        }

    def _usage_hook(self, project_id: str, models: Sequence[ModelSpec], limit_usd: float):  # type: ignore[no-untyped-def]
        spent = {"usd": 0.0}

        async def record(task: Task, result: LlmResult, cached: bool) -> None:
            spec = find(list(models), result.model)
            price = 0.0 if cached else cost_usd(result.usage, spec)
            spent["usd"] += price
            async with self._sessions() as session:
                session.add(
                    UsageEvent(
                        project_id=project_id,
                        task=task,
                        model_id=result.model,
                        input_tokens=result.usage.input_tokens,
                        output_tokens=result.usage.output_tokens,
                        cache_write_tokens=result.usage.cache_write_tokens,
                        cache_read_tokens=result.usage.cache_read_tokens,
                        cost_usd=price,
                        cached=cached,
                    )
                )
                await session.commit()
                totals = await self.totals(session, project_id)
            self.publish(project_id, "usage", totals)
            if limit_usd > 0 and float(totals["cost_usd"]) > limit_usd:
                raise CostLimitError(
                    f"The cost limit of ${limit_usd:.2f} was reached. "
                    "Raise the limit to carry on, or open what has been built so far.",
                )

        return record

    # -------------------------------------------------------------- pipeline
    async def prepare(
        self, session: AsyncSession, project: Project
    ) -> tuple[CodeMap, ScanResult, dict[str, str], Path]:
        pdir = project_dir(self._settings, project.id)
        root = project_root(self._settings, project)
        scan = ScanResult.model_validate(project.scan or {})
        cm = load_codemap(pdir)
        if cm is None:
            cm = await asyncio.to_thread(build_codemap, root, scan)
            await asyncio.to_thread(save_codemap, cm, pdir)
            stats = cm.stats()
            payload = dict(project.scan or {})
            payload["function_count"] = stats["functions"]
            payload["class_count"] = stats["classes"]
            project.scan = payload
            project.codemap_ready = True
            await session.commit()
        return cm, scan, load_summaries(pdir), root

    async def _build_context(self, request: AnalysisRequest) -> RunContext | None:
        async with self._sessions() as session:
            project = await session.get(Project, request.project_id)
            if project is None:
                return None
            project.status = "analysing"
            project.error = None
            await session.commit()
            self.publish(
                request.project_id,
                "stage",
                {"stage": "parsing", "label": STAGE_LABELS["parsing"], "percent": 2},
            )
            cm, scan, summaries, root = await self.prepare(session, project)
            return RunContext(
                request=request,
                block=build_project_block(project, scan, cm),
                codemap=cm,
                summaries=summaries,
                root=root,
                usage=self._usage_hook(request.project_id, request.models, request.cost_limit_usd),
            )

    async def _run_summaries(self, ctx: RunContext, client: ClaudeClient) -> None:
        if ctx.summaries:
            return
        project_id = ctx.project_id
        self.publish(
            project_id,
            "stage",
            {"stage": "summaries", "label": STAGE_LABELS["summaries"], "percent": 10},
        )

        async def progress(item: str, fraction: float) -> None:
            self.publish(
                project_id,
                "progress",
                {"stage": "summaries", "item": item, "percent": round(10 + 50 * fraction, 1)},
            )

        async with self._sessions() as session:
            generator = SummaryGenerator(
                client=client,
                cache=ResponseCache(session),
                model=ctx.request.deep_model_id,
                project_block=ctx.block,
                on_usage=ctx.usage,
                effort=self._effort_for(ctx.request.deep_model_id, ctx.request.models, "low"),
            )
            functions = await generator.summarise_functions(
                ctx.codemap, ctx.root, progress=progress
            )
            ctx.summaries.update(functions.summaries)
            files = await generator.summarise_files(ctx.codemap, ctx.summaries)
            ctx.summaries.update(files.summaries)
            modules = await generator.summarise_modules(ctx.codemap, ctx.summaries)
            ctx.summaries.update(modules.summaries)
        await asyncio.to_thread(
            save_summaries, ctx.summaries, project_dir(self._settings, project_id)
        )

    async def _run_top_flow(self, ctx: RunContext) -> list[FlowNode]:
        self.publish(
            ctx.project_id,
            "stage",
            {"stage": "top_flow", "label": STAGE_LABELS["top_flow"], "percent": 62},
        )
        async with self._sessions() as session:
            existing = await load_children(session, ctx.project_id, None)
            if existing:
                return existing
            result = await self._generator(session, ctx).generate_system_flow()
            await persist(session, result)
            self.publish(
                ctx.project_id,
                "nodes",
                {"parent_id": None, "count": len(result.nodes), "percent": 75},
            )
            return result.nodes

    async def run_analysis(self, request: AnalysisRequest) -> None:
        project_id = request.project_id
        client: ClaudeClient | None = None
        try:
            ctx = await self._build_context(request)
            if ctx is None:
                return
            client = make_client(self._settings, request.api_key)
            await self._run_summaries(ctx, client)
            top_nodes = await self._run_top_flow(ctx)
            self.publish(project_id, "graph_ready", {"percent": 78})
            await self._generate_deeper(ctx, top_nodes)

            async with self._sessions() as session:
                project = await session.get(Project, project_id)
                if project is not None:
                    project.status = "ready"
                    await session.commit()
                totals = await self.totals(session, project_id)
            self.publish(project_id, "done", {"percent": 100, **totals})
        except asyncio.CancelledError:
            await self._mark(project_id, "cancelled", "Analysis was cancelled.")
            self.publish(project_id, "cancelled", {})
            raise
        except CostLimitError as exc:
            await self._mark(project_id, "paused", exc.message)
            self.publish(project_id, "limit_reached", {"message": exc.message})
        except LlmError as exc:
            await self._mark(project_id, "error", exc.message)
            self.publish(project_id, "error", {"message": exc.message, "code": exc.code})
        except Exception as exc:  # pragma: no cover - unexpected, logged and surfaced safely
            log.exception("analysis_failed", project_id=project_id, error=str(exc))
            await self._mark(
                project_id, "error", "Something went wrong while analysing this project."
            )
            self.publish(
                project_id,
                "error",
                {"message": "Something went wrong while analysing this project."},
            )
        finally:
            if client is not None:
                await client.aclose()

    def _effort_for(self, model_id: str, models: Sequence[ModelSpec], level: str) -> str | None:
        spec = find(list(models), model_id)
        return level if spec is not None and spec.supports_effort else None

    def _generator(self, session: AsyncSession, ctx: RunContext) -> FlowGenerator:
        request = ctx.request
        return FlowGenerator(
            client=make_client(self._settings, request.api_key),
            cache=ResponseCache(session),
            project_id=ctx.project_id,
            project_block=ctx.block,
            codemap=ctx.codemap,
            summaries=ctx.summaries,
            root=ctx.root,
            top_model=request.model_id,
            deep_model=request.deep_model_id,
            on_usage=ctx.usage,
            top_effort=self._effort_for(request.model_id, request.models, "medium"),
            deep_effort=self._effort_for(request.deep_model_id, request.models, "low"),
        )

    async def _generate_deeper(self, ctx: RunContext, top_nodes: list[FlowNode]) -> None:
        """Breadth-first pre-generation, bounded by BACKGROUND_MAX_NODES."""
        project_id = ctx.project_id
        self.publish(
            project_id,
            "stage",
            {"stage": "deeper_levels", "label": STAGE_LABELS["deeper_levels"], "percent": 80},
        )
        queue = [n for n in top_nodes if n.has_children]
        made = len(top_nodes)
        while queue and made < self._settings.background_max_nodes:
            node = queue.pop(0)
            if self._runner.is_cancelled(job_key(project_id)):
                raise asyncio.CancelledError
            async with self._sessions() as session:
                fresh = await session.get(FlowNode, node.id)
                if fresh is None:
                    continue
                if await load_children(session, project_id, node.id):
                    continue
                generator = self._generator(session, ctx)
                try:
                    result = await generator.expand_node(fresh)
                except LlmError as exc:
                    fresh.status = "error"
                    fresh.error = exc.message
                    await session.commit()
                    self.publish(
                        project_id, "node_error", {"node_id": fresh.id, "message": exc.message}
                    )
                    continue
                await persist(session, result)
                made += len(result.nodes)
                queue.extend(n for n in result.nodes if n.has_children)
                percent = min(99.0, 80 + 19 * made / max(1, self._settings.background_max_nodes))
                self.publish(
                    project_id,
                    "nodes",
                    {
                        "parent_id": fresh.id,
                        "count": len(result.nodes),
                        "percent": round(percent, 1),
                    },
                )

    async def expand_on_demand(self, request: AnalysisRequest, node_id: str) -> list[FlowNode]:
        """Generate one node's children right now (used when the user clicks an unbuilt node)."""
        project_id = request.project_id
        async with self._sessions() as session:
            project = await session.get(Project, project_id)
            node = await session.get(FlowNode, node_id)
            if project is None or node is None:
                return []
            existing = await load_children(session, project_id, node_id)
            if existing:
                return existing
            cm, scan, summaries, root = await self.prepare(session, project)
            node.status = "generating"
            await session.commit()
            self.publish(project_id, "node_generating", {"node_id": node_id})
            ctx = RunContext(
                request=request,
                block=build_project_block(project, scan, cm),
                codemap=cm,
                summaries=summaries,
                root=root,
                usage=self._usage_hook(project_id, request.models, request.cost_limit_usd),
            )
            generator = self._generator(session, ctx)
            try:
                result = await generator.expand_node(node)
            except LlmError as exc:
                node.status = "error"
                node.error = exc.message
                await session.commit()
                self.publish(project_id, "node_error", {"node_id": node_id, "message": exc.message})
                raise
            await persist(session, result)
            node.status = "ready"
            node.has_children = bool(result.nodes)
            await session.commit()
            self.publish(project_id, "nodes", {"parent_id": node_id, "count": len(result.nodes)})
            return result.nodes

    async def _mark(self, project_id: str, status: str, error: str | None) -> None:
        async with self._sessions() as session:
            project = await session.get(Project, project_id)
            if project is not None:
                project.status = status
                project.error = error
                await session.commit()

    # --------------------------------------------------------------- control
    def submit_analysis(self, request: AnalysisRequest) -> bool:
        self._runner.resume(job_key(request.project_id))

        async def run() -> None:
            await self.run_analysis(request)

        return self._runner.submit(job_key(request.project_id), run, priority=PRIORITY_BACKGROUND)

    def submit_expansion(self, request: AnalysisRequest, node_id: str) -> bool:
        async def run() -> None:
            # errors are already reported on the event stream and stored on the node
            with contextlib.suppress(LlmError):
                await self.expand_on_demand(request, node_id)

        return self._runner.submit(
            job_key(request.project_id, f":node:{node_id}"), run, priority=PRIORITY_INTERACTIVE
        )

    def cancel(self, project_id: str) -> None:
        self._runner.cancel_group(job_key(project_id))
        self.publish(project_id, "cancelled", {})

    async def reset_graph(self, session: AsyncSession, project_id: str) -> None:
        await session.execute(delete(FlowEdge).where(FlowEdge.project_id == project_id))
        await session.execute(delete(FlowNode).where(FlowNode.project_id == project_id))
        await session.commit()
