"""Per-host politeness.

Two limits per host, because they solve different problems: a delay between
request starts keeps the average rate down, and a semaphore caps how many
requests are in flight at once. Shared across a whole crawl so twenty
chapters queued in parallel still behave.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class _HostState:
    semaphore: asyncio.Semaphore
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_allowed_at: float = 0.0


class DomainThrottle:
    """Rate limit and concurrency cap, keyed by host.

    ``sleep`` and ``monotonic`` are injectable so tests can assert on the
    delays without actually waiting.
    """

    def __init__(
        self,
        *,
        delay: float = 0.6,
        concurrency: int = 4,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self._delay = max(delay, 0.0)
        self._concurrency = concurrency
        self._sleep = sleep or asyncio.sleep
        self._monotonic = monotonic or time.monotonic
        self._hosts: dict[str, _HostState] = {}
        self._hosts_lock = asyncio.Lock()

    async def _state_for(self, host: str) -> _HostState:
        async with self._hosts_lock:
            state = self._hosts.get(host)
            if state is None:
                state = _HostState(semaphore=asyncio.Semaphore(self._concurrency))
                self._hosts[host] = state
            return state

    @asynccontextmanager
    async def slot(self, host: str):
        """Hold a concurrency slot for ``host``, waiting out the delay first."""
        state = await self._state_for(host)
        async with state.semaphore:
            if self._delay > 0:
                # Reserve this host's next start time while holding the lock so
                # concurrent callers queue up instead of all firing at once.
                async with state.lock:
                    now = self._monotonic()
                    wait = state.next_allowed_at - now
                    start = now if wait <= 0 else state.next_allowed_at
                    state.next_allowed_at = start + self._delay
                if wait > 0:
                    await self._sleep(wait)
            yield
