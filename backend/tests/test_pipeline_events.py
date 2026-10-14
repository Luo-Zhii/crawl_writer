"""Progress event fan-out."""

from __future__ import annotations

import asyncio

from app.pipeline.events import EventHub, Progress


def make(job_id: int = 1, **kwargs) -> Progress:
    return Progress(job_id=job_id, status="running", **kwargs)


def test_percent_and_processed():
    event = make(total=10, done=3, failed=1, skipped=1)

    assert event.processed == 5
    assert event.percent == 50.0


def test_percent_with_no_total_does_not_divide_by_zero():
    assert make(total=0).percent == 0.0


def test_to_dict_includes_derived_fields():
    payload = make(total=4, done=1).to_dict()

    assert payload["processed"] == 1
    assert payload["percent"] == 25.0
    assert payload["job_id"] == 1


async def test_subscriber_receives_events():
    hub = EventHub()

    async with hub.subscribe(1) as queue:
        hub.publish(make(done=1))

        event = await asyncio.wait_for(queue.get(), timeout=1)

    assert event.done == 1


async def test_events_go_only_to_the_matching_job():
    hub = EventHub()

    async with hub.subscribe(1) as queue:
        hub.publish(make(job_id=2, done=9))
        hub.publish(make(job_id=1, done=1))

        event = await asyncio.wait_for(queue.get(), timeout=1)

    assert event.done == 1, "should not have received job 2's event"


async def test_multiple_subscribers_each_get_a_copy():
    hub = EventHub()

    async with hub.subscribe(1) as first, hub.subscribe(1) as second:
        assert hub.subscriber_count(1) == 2
        hub.publish(make(done=7))

        assert (await first.get()).done == 7
        assert (await second.get()).done == 7


async def test_unsubscribing_cleans_up():
    hub = EventHub()

    async with hub.subscribe(1):
        pass

    assert hub.subscriber_count(1) == 0
    # Publishing with nobody listening must not raise.
    hub.publish(make())


async def test_close_ends_the_stream():
    hub = EventHub()
    received = []

    async def consume() -> None:
        async for event in hub.stream(1):
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    hub.publish(make(done=1))
    await asyncio.sleep(0)
    hub.close(1)
    await asyncio.wait_for(task, timeout=1)

    assert len(received) == 1


async def test_slow_subscriber_does_not_block_publishing():
    """A stalled browser tab must never hold up the crawl."""
    hub = EventHub()

    async with hub.subscribe(1) as queue:
        for index in range(500):  # more than the queue holds
            hub.publish(make(done=index))

        assert queue.qsize() > 0  # events were delivered, extras dropped
