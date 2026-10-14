"""Pause and cancel, handled cooperatively.

A crawl is a long loop over chapters, so stopping it means asking it to stop
at the next chapter boundary rather than killing a task mid-write. That keeps
the database and the files on disk agreeing with each other.
"""

from __future__ import annotations

import asyncio


class JobCancelled(Exception):
    """Raised inside a running job once cancellation is requested."""


class JobControl:
    """Pause/cancel switches for one running job."""

    def __init__(self) -> None:
        self._cancelled = asyncio.Event()
        # "Resumed" rather than "paused" so the common case is a no-wait await.
        self._resumed = asyncio.Event()
        self._resumed.set()

    # --- state ------------------------------------------------------------

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def paused(self) -> bool:
        return not self._resumed.is_set()

    # --- requests ---------------------------------------------------------

    def cancel(self) -> None:
        self._cancelled.set()
        # Let a paused job wake up and notice it was cancelled.
        self._resumed.set()

    def pause(self) -> None:
        self._resumed.clear()

    def resume(self) -> None:
        self._resumed.set()

    # --- used by the runner -----------------------------------------------

    async def checkpoint(self) -> None:
        """Call between chapters: waits while paused, raises if cancelled."""
        if self._cancelled.is_set():
            raise JobCancelled
        if not self._resumed.is_set():
            await self._resumed.wait()
        if self._cancelled.is_set():
            raise JobCancelled

    async def wait_cancelled(self) -> None:
        """Resolve once cancellation is requested.

        Lets the runner interrupt a request that is already in flight instead
        of waiting for it to time out first.
        """
        await self._cancelled.wait()
