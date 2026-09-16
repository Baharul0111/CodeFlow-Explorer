"""Project endpoints: upload (unzip + scan), list, get, delete."""

from __future__ import annotations

import re
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import Response

from app.api.deps import ClientKeyDep, LimiterDep, SessionDep, SettingsDep
from app.api.errors import AppError, PayloadTooLargeError
from app.api.schemas import ProjectListItem, ProjectOut, ScanSummary
from app.models.orm import Project
from app.pipeline.projects import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    scan_summary,
)
from app.pipeline.scan import ScanResult

router = APIRouter(prefix="/api/projects", tags=["projects"])
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def _clean_name(filename: str | None) -> str:
    base = (filename or "project.zip").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = re.sub(r"\.zip$", "", base, flags=re.IGNORECASE)
    cleaned = SAFE_NAME.sub("_", base).strip(" ._") or "project"
    return cleaned[:80]


def project_out(project: Project) -> ProjectOut:
    scan_data = project.scan
    summary: ScanSummary | None = None
    if scan_data:
        scan = ScanResult.model_validate(scan_data)
        summary = scan_summary(
            scan,
            function_count=scan_data.get("function_count"),
            class_count=scan_data.get("class_count"),
        )
    return ProjectOut(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        updated_at=project.updated_at,
        upload_bytes=project.upload_bytes,
        status=project.status,
        model_id=project.model_id,
        deep_model_id=project.deep_model_id,
        scan=summary,
        estimate=project.estimate,
        error=project.error,
    )


async def _spool_upload(file: UploadFile, dest: Path, max_bytes: int) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    async with aiofiles.open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise PayloadTooLargeError(
                    f"This file is larger than {max_bytes // (1024 * 1024)} MB. "
                    "Please upload a smaller zip."
                )
            await out.write(chunk)
    return total


@router.post("", response_model=ProjectOut, status_code=201)
async def upload_project(  # noqa: PLR0917 - FastAPI resolves these by name
    request: Request,
    file: UploadFile,
    session: SessionDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    key: ClientKeyDep,
) -> ProjectOut:
    limiter.check(f"upload:{key}", settings.rate_limit_uploads_per_minute)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes + 4096:
        raise PayloadTooLargeError(
            f"This file is larger than {settings.max_upload_mb} MB. Please upload a smaller zip."
        )
    if file.content_type not in (None, "application/zip", "application/x-zip-compressed",
                                 "application/octet-stream", "multipart/x-zip"):  # fmt: skip
        raise AppError("Please upload a .zip file.", code="not_a_zip")
    tmp = settings.workspace_dir / "_uploads" / f"{id(file)}.zip"
    try:
        size = await _spool_upload(file, tmp, settings.max_upload_bytes)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    project, _scan = await create_project(
        session, settings, zip_path=tmp, name=_clean_name(file.filename), upload_bytes=size
    )
    return project_out(project)


@router.get("", response_model=list[ProjectListItem])
async def get_projects(session: SessionDep) -> list[ProjectListItem]:
    rows = await list_projects(session)
    return [
        ProjectListItem(
            id=p.id,
            name=p.name,
            created_at=p.created_at,
            status=p.status,
            model_id=p.model_id,
            file_count=len((p.scan or {}).get("files", [])),
            node_count=nodes,
            total_cost_usd=round(cost, 4),
        )
        for p, nodes, cost in rows
    ]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_one(project_id: str, session: SessionDep) -> ProjectOut:
    return project_out(await get_project(session, project_id))


@router.delete("/{project_id}", status_code=204)
async def delete_one(project_id: str, session: SessionDep, settings: SettingsDep) -> Response:
    project = await get_project(session, project_id)
    await delete_project(session, settings, project)
    return Response(status_code=204)
