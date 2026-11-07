"""Tests for the event bus.

The bus is the only thing that tells a waiting caller what the
appliance is doing while it spends 54-200 seconds on one image, so the
tests are about two promises: the right session hears about the right
event, and nobody who is listening is ever left out.
"""
from __future__ import annotations

import dataclasses
import queue
import threading

import pytest

from tis.events import EVENT_TYPES, Event, EventBus


def test_publish_reaches_the_subscriber_of_that_session():
    bus = EventBus()
    q = bus.subscribe("s1")

    event = bus.publish("job.started", "s1", {"job_id": "job_1"})

    delivered = q.get_nowait()
    assert delivered is event
    assert delivered.type == "job.started"
    assert delivered.session_id == "s1"
    assert delivered.data == {"job_id": "job_1"}
    assert delivered.ts > 0


def test_a_subscriber_of_another_session_does_not_receive_it():
    bus = EventBus()
    mine = bus.subscribe("s1")
    theirs = bus.subscribe("s2")

    bus.publish("job.started", "s1")

    assert mine.get_nowait().session_id == "s1"
    with pytest.raises(queue.Empty):
        theirs.get_nowait()


def test_publishing_with_no_subscribers_is_not_an_error():
    """A job can finish before anybody opens the stream."""
    bus = EventBus()

    event = bus.publish("job.finished", "nobody-is-listening")

    assert event.type == "job.finished"
    assert event.session_id == "nobody-is-listening"


def test_unsubscribe_stops_delivery_and_closes_the_queue():
    bus = EventBus()
    q = bus.subscribe("s1")
    bus.publish("job.started", "s1")

    bus.unsubscribe("s1")
    bus.publish("job.finished", "s1")

    with pytest.raises(ValueError):
        q.get()


def test_unsubscribe_for_a_session_with_no_subscribers_is_not_an_error():
    EventBus().unsubscribe("never-subscribed")


def test_two_subscribers_of_the_same_session_both_receive_the_event():
    """A browser tab and a script watch the same session."""
    bus = EventBus()
    first = bus.subscribe("s1")
    second = bus.subscribe("s1")
    assert first is not second

    event = bus.publish("plan.ready", "s1")

    assert first.get_nowait() is event
    assert second.get_nowait() is event


def test_the_ids_start_at_one_and_increase():
    bus = EventBus()

    ids = [bus.publish("job.queued", "s1").id for _ in range(3)]

    assert ids[0] == "000000000001"
    assert ids[1] == "000000000002"
    assert ids[2] == "000000000003"
    assert all(len(i) == 12 for i in ids)
    # Zero-padded, so the ids also sort correctly as strings.
    assert ids == sorted(ids)


def test_the_id_orders_events_that_share_a_timestamp():
    """Two events inside the same second still have an order."""
    bus = EventBus()
    q = bus.subscribe("s1")

    events = [bus.publish("swap.started", "s1"),
              bus.publish("swap.finished", "s1")]

    assert int(events[0].id) < int(events[1].id)
    assert q.get_nowait() is events[0]
    assert q.get_nowait() is events[1]


def test_a_publisher_racing_a_subscribe_and_unsubscribe_loses_nothing():
    """The bus is used from a worker thread while a client comes and goes."""
    bus = EventBus()
    keeper = bus.subscribe("keeper")
    errors: list[BaseException] = []

    def churn() -> None:
        try:
            for _ in range(200):
                bus.subscribe("churn")
                bus.publish("job.started", "churn")
                bus.unsubscribe("churn")
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    def publish() -> None:
        try:
            for i in range(200):
                bus.publish("generate.started", "keeper", {"i": i})
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    workers = [threading.Thread(target=churn),
               threading.Thread(target=publish)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    assert [w.is_alive() for w in workers] == [False, False]
    assert errors == []

    received = [keeper.get_nowait() for _ in range(200)]
    assert [e.data["i"] for e in received] == list(range(200))


def test_concurrent_publishers_get_distinct_ids():
    bus = EventBus()
    q = bus.subscribe("s1")
    published: list[Event] = []

    def publish() -> None:
        for _ in range(100):
            published.append(bus.publish("generate.started", "s1"))

    workers = [threading.Thread(target=publish) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    ids = [e.id for e in published]
    assert len(ids) == 400
    assert len(set(ids)) == 400
    assert q.qsize() == 400


def test_a_subscriber_that_falls_behind_loses_nothing():
    """The queues are unbounded: a slow reader reads late, not short."""
    bus = EventBus()
    q = bus.subscribe("s1")

    for i in range(500):
        bus.publish("generate.started", "s1", {"i": i})

    drained = []
    while True:
        try:
            drained.append(q.get_nowait())
        except queue.Empty:
            break
    assert [e.data["i"] for e in drained] == list(range(500))


def test_the_registry_lock_is_released_before_a_slow_put():
    """A slow consumer must not stall the rest of the bus.

    The queues are unbounded, so a put cannot really block — but if the
    registry lock were held across it, one slow reader would stop
    every other publisher and subscriber.
    """
    bus = EventBus()
    q = bus.subscribe("s1")
    entered = threading.Event()
    release = threading.Event()

    def slow_put(item):
        entered.set()
        release.wait(timeout=10)
        queue.Queue.put_nowait(q, item)

    q.put_nowait = slow_put  # type: ignore[method-assign]

    publisher = threading.Thread(target=lambda: bus.publish("job.started", "s1"))
    publisher.start()
    try:
        assert entered.wait(timeout=10)

        # The publish is still inside its put; anything else that needs
        # the registry must not be waiting for it.
        subscribed = []
        other = threading.Thread(
            target=lambda: subscribed.append(bus.subscribe("s2")))
        other.start()
        other.join(timeout=10)

        assert not other.is_alive()
        assert len(subscribed) == 1
    finally:
        release.set()
        publisher.join(timeout=10)


def test_the_event_carries_exactly_the_documented_fields():
    assert [f.name for f in dataclasses.fields(Event)] == [
        "id", "type", "session_id", "data", "ts"]


def test_the_documented_vocabulary_is_publishable():
    bus = EventBus()
    q = bus.subscribe("s1")

    for event_type in sorted(EVENT_TYPES):
        bus.publish(event_type, "s1")

    assert q.qsize() == len(EVENT_TYPES)


def test_unsubscribing_one_subscriber_leaves_the_others_alone():
    """A browser tab and a script can watch the same session.

    The first one disconnecting must not take the second one with it —
    that is what a session is for, and the module's own docstring says
    so.
    """
    bus = EventBus()
    tab = bus.subscribe("s1")
    script = bus.subscribe("s1")

    bus.unsubscribe_queue(tab)

    event = bus.publish("job.started", "s1", {})
    assert script.get(timeout=1) is event
    # The dropped subscriber's queue is closed, and says so.
    with pytest.raises(ValueError):
        tab.get(timeout=1)


def test_unsubscribing_a_queue_from_a_session_with_one_subscriber_clears_it():
    bus = EventBus()
    only = bus.subscribe("s1")
    bus.unsubscribe_queue(only)
    # Publishing now reaches nobody, and does not raise.
    bus.publish("job.started", "s1", {})
    with pytest.raises(ValueError):
        only.get(timeout=1)


def test_a_late_subscriber_is_caught_up_first():
    """The stream is a window onto a session, not a feed that starts when
    the listener arrives.

    A client that POSTs a job and THEN opens the stream would otherwise
    miss everything published in between - and that is exactly the order
    the API documents. So the session's recent events are replayed to a
    late subscriber before it is given anything new.
    """
    bus = EventBus()
    bus.publish("job.queued", "s1", {"job_id": "job_1"})
    bus.publish("job.started", "s1", {"job_id": "job_1"})

    late = bus.subscribe("s1")
    assert late.get(timeout=1).type == "job.queued"
    assert late.get(timeout=1).type == "job.started"


def test_the_replay_is_bounded():
    """The history is a window, not a log."""
    bus = EventBus(history=4)
    for index in range(10):
        bus.publish("job.queued", "s1", {"n": index})

    late = bus.subscribe("s1")
    replayed = []
    while True:
        try:
            replayed.append(late.get(timeout=0.2))
        except Exception:
            break
    assert len(replayed) == 4
    assert replayed[0].data["n"] == 6


def test_a_late_subscriber_of_another_session_gets_nothing():
    """The history is per session. A late subscriber is caught up on its
    OWN session, never on somebody else's."""
    bus = EventBus()
    bus.publish("job.queued", "s1", {"job_id": "job_1"})

    other = bus.subscribe("s2")
    with pytest.raises(Exception):
        other.get(timeout=0.3)
