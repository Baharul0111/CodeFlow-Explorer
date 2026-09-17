"""In-process job runner: an asyncio priority queue with a concurrency limit.

On-demand expansions (the user clicked a node) jump ahead of background breadth-first work. The
``JobRunner`` interface is deliberately small so it can be swapped for Celery/arq later without
touching the pipeline.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from app.logging_setup import get_logger

log = get_logger(__name__)

PRIORITY_INTERACTIVE = 0
PRIORITY_BACKGROUND = 10


@dataclass(order=True)
class _QueuedJob:
    priority: int
    sequence: int
    key: str = field(compare=False)
    run: Callable[[], Coroutine[Any, Any, None]] = field(compare=False)


class JobRunner:
    """Runs queued coroutines with a fixed number of workers."""

    def __init__(self, concurrency: int = 4) -> None:
        self._queue: asyncio.PriorityQueue[_QueuedJob] = asyncio.PriorityQueue()
        self._concurrency = max(1, concurrency)
        self._workers: list[asyncio.Task[None]] = []
        self._sequence = count()
        self._queued_keys: set[str] = set()
        self._cancelled: set[str] = set()
        self._running: dict[str, asyncio.Task[None]] = {}

    async def start(self) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(i), name=f"job-worker-{i}")
            for i in range(self._concurrency)
        ]

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._workers.clear()

    def submit(
        self,
        key: str,
        run: Callable[[], Coroutine[Any, Any, None]],
        *,
        priority: int = PRIORITY_BACKGROUND,
    ) -> bool:
        """Queue a job. Returns False when an identical job is already queued."""
        if key in self._queued_keys or key in self._running:
            return False
        self._queued_keys.add(key)
        self._cancelled.discard(key)
        self._queue.put_nowait(
            _QueuedJob(priority=priority, sequence=next(self._sequence), key=key, run=run)
        )
        return True

    def cancel_group(self, prefix: str) -> None:
        """Cancel queued and running jobs whose key starts with ``prefix`` (e.g. one project)."""
        self._cancelled.add(prefix)
        for key, task in list(self._running.items()):
            if key.startswith(prefix):
                task.cancel()

    def is_cancelled(self, key: str) -> bool:
        return any(key.startswith(prefix) for prefix in self._cancelled)

    def resume(self, prefix: str) -> None:
        self._cancelled.discard(prefix)

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def _worker(self, index: int) -> None:
        while True:
            job = await self._queue.get()
            self._queued_keys.discard(job.key)
            if self.is_cancelled(job.key):
                self._queue.task_done()
                continue
            task: asyncio.Task[None] = asyncio.create_task(job.run(), name=f"job:{job.key}")
            self._running[job.key] = task
            try:
                await task
            except asyncio.CancelledError:
                log.info("job_cancelled", key=job.key, worker=index)
            except Exception as exc:  # a failing job must not kill its worker
                log.exception("job_failed", key=job.key, worker=index, error=str(exc))
            finally:
                self._running.pop(job.key, None)
                self._queue.task_done()

    async def drain(self) -> None:
        """Wait for everything queued so far (used by tests and the CLI runner)."""
        await self._queue.join()
