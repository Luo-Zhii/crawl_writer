"""Per-host pacing and concurrency.

A fake clock keeps these tests instant: nothing here should actually sleep.
"""

from __future__ import annotations

import asyncio

import pytest

from app.fetch.throttle import DomainThrottle


class FakeClock:
    """Virtual clock that records sleeps instead of performing them.

    Sleeping deliberately does *not* advance the clock: these tests care about
    waiters that all arrive at roughly the same instant, which is what happens
    when a crawl queues twenty chapters at once. Advancing on every sleep would
    turn that into a sequential walk and hide the spacing we want to assert.
    Call :meth:`advance` when a test needs time to pass.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def make_throttle(delay: float = 1.0, concurrency: int = 4) -> tuple[DomainThrottle, FakeClock]:
    clock = FakeClock()
    throttle = DomainThrottle(
        delay=delay, concurrency=concurrency, sleep=clock.sleep, monotonic=clock.monotonic
    )
    return throttle, clock


async def test_first_request_does_not_wait():
    throttle, clock = make_throttle()

    async with throttle.slot("a.test"):
        pass

    assert clock.sleeps == []


async def test_second_request_to_same_host_waits_the_delay():
    throttle, clock = make_throttle(delay=1.0)

    async with throttle.slot("a.test"):
        pass
    async with throttle.slot("a.test"):
        pass

    assert clock.sleeps == [1.0]


async def test_hosts_are_paced_independently():
    """One slow site must not hold up chapters from another."""
    throttle, clock = make_throttle(delay=1.0)

    async with throttle.slot("a.test"):
        pass
    async with throttle.slot("b.test"):
        pass

    assert clock.sleeps == []


async def test_parallel_requests_are_spaced_not_simultaneous():
    """Four chapters queued at once must start one delay apart, not together."""
    throttle, clock = make_throttle(delay=1.0, concurrency=4)

    async def hit() -> None:
        async with throttle.slot("a.test"):
            pass

    await asyncio.gather(*(hit() for _ in range(4)))

    # First goes immediately; the rest wait for their reserved slot.
    assert sorted(clock.sleeps) == [1.0, 2.0, 3.0]


async def test_pacing_accounts_for_time_already_elapsed():
    """If a request took longer than the delay, the next one should not wait."""
    throttle, clock = make_throttle(delay=1.0)

    async with throttle.slot("a.test"):
        pass
    clock.advance(5.0)
    async with throttle.slot("a.test"):
        pass

    assert clock.sleeps == []


async def test_zero_delay_disables_pacing():
    throttle, clock = make_throttle(delay=0.0)

    for _ in range(3):
        async with throttle.slot("a.test"):
            pass

    assert clock.sleeps == []


async def test_concurrency_cap_is_enforced():
    throttle, _ = make_throttle(delay=0.0, concurrency=2)
    in_flight = 0
    peak = 0

    async def hit() -> None:
        nonlocal in_flight, peak
        async with throttle.slot("a.test"):
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)  # let siblings run
            in_flight -= 1

    await asyncio.gather(*(hit() for _ in range(6)))

    assert peak == 2


async def test_slot_is_released_when_the_body_raises():
    """A failed chapter must not leak a concurrency slot."""
    throttle, _ = make_throttle(delay=0.0, concurrency=1)

    with pytest.raises(RuntimeError):
        async with throttle.slot("a.test"):
            raise RuntimeError("boom")

    async with throttle.slot("a.test"):
        pass  # would deadlock if the slot had leaked


def test_concurrency_must_be_positive():
    with pytest.raises(ValueError):
        DomainThrottle(concurrency=0)
