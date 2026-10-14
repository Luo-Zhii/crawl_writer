"""Progress events for the UI.

In-memory pub/sub, one topic per job. The SSE endpoint subscribes; the crawl
runner publishes. Durable state lives in the ``job`` row, so a dropped
subscriber loses nothing it cannot read back.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

# Dropped rather than blocking the crawl when a subscriber stops reading.
_QUEUE_SIZE = 256


@dataclass(slots=True)
class Progress:
    """A snapshot of a job, shaped for direct JSON serialisation."""

    job_id: int
    status: str
    total: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0
    #: Short human-readable note, e.g. "fetching chapter 12" or a block reason.
    message: str | None = None
    #: Set when the event concerns one chapter.
    chapter: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def processed(self) -> int:
        return self.done + self.failed + self.skipped

    @property
    def percent(self) -> float:
        return round(self.processed / self.total * 100, 1) if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["processed"] = self.processed
        payload["percent"] = self.percent
        return payload


class EventHub:
    """Fan-out of :class:`Progress` events to any number of listeners."""

    def __init__(self) -> None:
        self._topics: dict[int, set[asyncio.Queue[Progress | None]]] = {}

    def publish(self, event: Progress) -> None:
        for queue in list(self._topics.get(event.job_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A slow reader must never stall the crawl.
                log.debug("dropping progress event for job %s: subscriber full", event.job_id)

    def close(self, job_id: int) -> None:
        """Signal end-of-stream so subscribers can finish cleanly."""
        for queue in list(self._topics.get(job_id, ())):
            # A full queue means the subscriber stopped reading; it will see
            # the stream end when it disconnects.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)

    def subscriber_count(self, job_id: int) -> int:
        return len(self._topics.get(job_id, ()))

    @asynccontextmanager
    async def subscribe(self, job_id: int):
        queue: asyncio.Queue[Progress | None] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._topics.setdefault(job_id, set()).add(queue)
        try:
            yield queue
        finally:
            listeners = self._topics.get(job_id)
            if listeners is not None:
                listeners.discard(queue)
                if not listeners:
                    del self._topics[job_id]

    async def stream(self, job_id: int) -> AsyncIterator[Progress]:
        """Yield events until the job closes its topic."""
        async with self.subscribe(job_id) as queue:
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
