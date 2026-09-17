"""Delete workspaces (and their projects) older than WORKSPACE_RETENTION_DAYS."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

from app.config import Settings
from app.logging_setup import get_logger

log = get_logger(__name__)


def _remove_old(workspace_dir: Path, max_age_seconds: float) -> int:
    if not workspace_dir.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for child in workspace_dir.iterdir():
        if not child.is_dir() or child.name.startswith("_") or child.name.startswith("."):
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:  # pragma: no cover - racing with another delete
            continue
    return removed


async def cleanup_old_workspaces(settings: Settings) -> int:
    days = max(0, settings.workspace_retention_days)
    if days == 0:
        return 0
    removed = await asyncio.to_thread(_remove_old, settings.workspace_dir, days * 86_400)
    if removed:
        log.info("workspaces_cleaned", removed=removed, retention_days=days)
    return removed
