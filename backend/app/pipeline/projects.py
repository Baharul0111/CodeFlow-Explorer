"""Project lifecycle: create from an uploaded zip, list, load, delete."""

from __future__ import annotations

import asyncio
import secrets
import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import NotFoundError
from app.api.schemas import ScanSummary
from app.config import Settings
from app.models.orm import FlowNode, Project, UsageEvent
from app.pipeline.scan import ScanLimits, ScanResult, scan_project
from app.pipeline.unzip import ZipLimits, safe_extract


def new_id() -> str:
    return secrets.token_hex(8)


def project_dir(settings: Settings, project_id: str) -> Path:
    return settings.workspace_dir / project_id


def project_root(settings: Settings, project: Project) -> Path:
    """Root of the extracted sources (may be a nested folder inside src/)."""
    scan = project.scan or {}
    root = scan.get("root")
    return Path(root) if root else project_dir(settings, project.id) / "src"


def scan_summary(scan: ScanResult, *, function_count: int | None = None,
                 class_count: int | None = None) -> ScanSummary:  # fmt: skip
    return ScanSummary(
        languages=scan.languages,
        file_count=len(scan.files),
        code_file_count=len(scan.code_files),
        function_count=function_count,
        class_count=class_count,
        skipped_counts=scan.skipped_counts,
        skipped_examples=scan.skipped[:50],
        frameworks=scan.frameworks,
        entry_hints=scan.entry_hints,
        readme_excerpt=scan.readme_excerpt,
    )


def _extract_and_scan(zip_path: Path, dest: Path, settings: Settings) -> ScanResult:
    limits = ZipLimits(
        max_unzipped_bytes=settings.max_unzipped_bytes,
        max_files=settings.max_files,
        max_compression_ratio=settings.max_compression_ratio,
    )
    extracted = safe_extract(zip_path, dest, limits)
    return scan_project(
        extracted.root,
        ScanLimits(max_file_bytes=settings.max_file_bytes, max_files=settings.max_files),
    )


async def create_project(
    session: AsyncSession, settings: Settings, *, zip_path: Path, name: str, upload_bytes: int
) -> tuple[Project, ScanResult]:
    project_id = new_id()
    pdir = project_dir(settings, project_id)
    src = pdir / "src"
    try:
        scan = await asyncio.to_thread(_extract_and_scan, zip_path, src, settings)
    except Exception:
        shutil.rmtree(pdir, ignore_errors=True)
        raise
    finally:
        await asyncio.to_thread(zip_path.unlink, True)
    scan_payload = scan.model_dump()
    scan_payload["skipped"] = scan_payload["skipped"][:300]
    project = Project(
        id=project_id,
        name=name,
        upload_bytes=upload_bytes,
        status="scanned",
        scan=scan_payload,
        cost_limit_usd=settings.max_cost_per_project_usd,
    )
    session.add(project)
    await session.commit()
    return project, scan


async def get_project(session: AsyncSession, project_id: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("This project does not exist (it may have been deleted).")
    return project


async def list_projects(session: AsyncSession) -> list[tuple[Project, int, float]]:
    node_counts = (
        select(FlowNode.project_id, func.count(FlowNode.id).label("n"))
        .group_by(FlowNode.project_id)
        .subquery()
    )
    costs = (
        select(UsageEvent.project_id, func.coalesce(func.sum(UsageEvent.cost_usd), 0.0).label("c"))
        .group_by(UsageEvent.project_id)
        .subquery()
    )
    stmt = (
        select(Project, func.coalesce(node_counts.c.n, 0), func.coalesce(costs.c.c, 0.0))
        .outerjoin(node_counts, node_counts.c.project_id == Project.id)
        .outerjoin(costs, costs.c.project_id == Project.id)
        .order_by(Project.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], int(row[1]), float(row[2])) for row in rows]


async def delete_project(session: AsyncSession, settings: Settings, project: Project) -> None:
    pdir = project_dir(settings, project.id)
    await session.delete(project)
    await session.commit()
    await asyncio.to_thread(shutil.rmtree, pdir, True)
