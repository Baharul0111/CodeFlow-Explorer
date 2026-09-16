from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import Settings

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "llm_mode": settings.llm_mode,
        "version": request.app.version,
    }
