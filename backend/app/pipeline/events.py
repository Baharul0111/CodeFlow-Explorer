"""In-process event bus for Server-Sent Events.

One bus per process; subscribers get their own queue plus a short replay buffer so a browser that
reconnects with ``Last-Event-ID`` does not miss progress.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from itertools import count
from typing import Any

REPLAY_SIZE = 200
QUEUE_SIZE = 500


@dataclass(slots=True)
class Event:
    id: int
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def sse(self) -> dict[str, str]:
        return {"id": str(self.id), "event": self.type, "data": json.dumps(self.data)}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)
        self._history: dict[str, deque[Event]] = defaultdict(lambda: deque(maxlen=REPLAY_SIZE))
        self._ids = count(1)

    def publish(self, channel: str, event_type: str, data: dict[str, Any] | None = None) -> Event:
        event = Event(id=next(self._ids), type=event_type, data=data or {})
        self._history[channel].append(event)
        for queue in list(self._subscribers[channel]):
            if queue.full():  # a slow reader must never block the pipeline
                continue
            queue.put_nowait(event)
        return event

    async def subscribe(
        self, channel: str, *, last_event_id: int | None = None
    ) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers[channel].add(queue)
        try:
            if last_event_id is not None:
                for event in list(self._history[channel]):
                    if event.id > last_event_id:
                        yield event
            while True:
                yield await queue.get()
        finally:
            self._subscribers[channel].discard(queue)

    def history(self, channel: str) -> list[Event]:
        return list(self._history[channel])

    def clear(self, channel: str) -> None:
        self._history.pop(channel, None)
