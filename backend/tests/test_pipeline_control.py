"""Pause/cancel switches."""

from __future__ import annotations

import asyncio

import pytest

from app.pipeline.control import JobCancelled, JobControl


async def test_fresh_control_runs_freely():
    control = JobControl()

    await control.checkpoint()  # must not block

    assert control.paused is False
    assert control.cancelled is False


async def test_cancel_raises_at_the_next_checkpoint():
    control = JobControl()
    control.cancel()

    with pytest.raises(JobCancelled):
        await control.checkpoint()


async def test_pause_blocks_until_resumed():
    control = JobControl()
    control.pause()
    assert control.paused is True

    waiting = asyncio.create_task(control.checkpoint())
    await asyncio.sleep(0)
    assert not waiting.done(), "a paused job should be waiting"

    control.resume()
    await waiting

    assert control.paused is False


async def test_cancelling_wakes_a_paused_job():
    """Otherwise a paused job could never be cancelled."""
    control = JobControl()
    control.pause()
    waiting = asyncio.create_task(control.checkpoint())
    await asyncio.sleep(0)

    control.cancel()

    with pytest.raises(JobCancelled):
        await waiting
