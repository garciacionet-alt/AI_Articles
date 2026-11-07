"""The event bus: how a waiting caller learns that something is happening.

The appliance takes 54-200 seconds to produce one image. A client that
waits on a synchronous request for that long is not waiting, it is
stuck, and it cannot tell a slow generation from a dead one. So the
app publishes progress — the plan is ready, the swap started, the
generation started, the critique is in — and the client watches the
stream for its own session.

This is deliberately the simplest thing that could work: in-process,
in memory, one process. It is not a broker, it survives no restart and
crosses no machine. Everything it needs, it does with a dict of queues.

TWO PROPERTIES ARE NOT NEGOTIABLE

ORDER. Several events land in the same second — a swap that starts and
finishes inside one tick, for instance — and the client still has to be
able to say which came first. So the bus owns a counter and stamps each
event with it; the id IS the order. The timestamp is for humans.

NO CONSUMER BLOCKS A PUBLISHER. The publisher is the worker that is
producing the image, and a subscriber that falls behind must not be
able to stall it. So the queues are unbounded, and the registry lock is
released before anything is put on a queue. A slow reader loses
nothing; it only reads late.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

#: The vocabulary of this build: the events the API publishes today.
#: The bus does not police it. A new event is an additive change to
#: what a client can understand, not a runtime fault — the same
#: judgement the registry makes about an artifact it has not heard of
#: (see ``models.Artifact._missing_``).
EVENT_TYPES: frozenset[str] = frozenset({
    "job.queued",
    "job.started",
    "plan.ready",
    "swap.started",
    "swap.finished",
    "generate.started",
    "generate.finished",
    "critique.ready",
    "asset.ready",
    "job.finished",
    "job.failed",
    "error",
})

#: The width of an event id. Zero-padded so the ids read as counters
#: and so they still sort correctly as strings.
ID_WIDTH = 12


@dataclass(frozen=True)
class Event:
    """One thing that happened, addressed to one session.

    ``id`` and ``ts`` are assigned by the bus and not by the caller:
    the id is the order, and a caller that supplied its own could not
    promise it was unique, monotonic, or shared with the other
    publishers of the same bus.
    """

    id: str
    type: str
    session_id: str
    data: dict[str, Any]
    ts: float

    def to_dict(self) -> dict[str, Any]:
        """The event as a plain dict, ready for JSON.

        The event knows its own shape, so it says so here rather than in
        every route that streams it.
        """
        return {
            "id": self.id,
            "type": self.type,
            "session_id": self.session_id,
            "data": self.data,
            "ts": self.ts,
        }


class _SubscriberQueue(queue.Queue):
    """A subscriber's queue, with a close that means something.

    ``queue.Queue`` grew ``close()`` in Python 3.13, and its closed
    queue raises ``QueueShutDown`` — which is not how the SSE route
    learns that a stream has ended. This project runs on 3.11, so the
    closure is ours to define: after ``close()`` the queue hands out
    nothing and raises ``ValueError``, and a publish that was already
    in flight when the queue closed is dropped rather than raised.

    Dropping rather than raising is the safe choice for the producer:
    the publisher is the worker doing the generation, and it must not
    fail because a client disconnected.
    """

    def __init__(self) -> None:
        super().__init__()
        self._closed = False
        # Its own condition, rather than the queue's: the queue's
        # internals are not the same across Python versions, and this
        # closure has to work on all of them.
        self._state = threading.Condition()

    @property
    def closed(self) -> bool:
        with self._state:
            return self._closed

    def close(self) -> None:
        """Close the queue and wake anybody waiting on it."""
        with self._state:
            self._closed = True
            # A reader blocked in get() would otherwise wait for an
            # event that will never come.
            self._state.notify_all()

    def put_nowait(self, item: Any) -> None:
        """Accept an event, unless the queue has been closed."""
        with self._state:
            if self._closed:
                return
            super().put_nowait(item)
            self._state.notify()

    def get(self, block: bool = True,
            timeout: Optional[float] = None) -> Any:
        """Take the next event, or raise once the queue is closed."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._state:
            while True:
                if self._closed:
                    raise ValueError("get() called on a closed queue")
                try:
                    return super().get(block=False)
                except queue.Empty:
                    pass
                if not block:
                    raise queue.Empty
                remaining: Optional[float] = None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise queue.Empty
                self._state.wait(remaining)


class EventBus:
    """The fan-out between the worker and the SSE route.

    One session may have several subscribers — a browser tab and a
    script, say — and each gets its own queue, so one slow reader
    cannot hold up another.
    """

    def __init__(self, history: int = 64) -> None:
        self._subscribers: dict[str, list[_SubscriberQueue]] = {}
        self._lock = threading.Lock()
        self._next_id = 1
        #: How many recent events each session remembers. A client that
        #: POSTS a job and THEN opens the stream would otherwise miss
        #: everything published in between - which is most of the
        #: interesting part. The stream is a window onto a session, not a
        #: feed that begins when the listener arrives, so a late
        #: subscriber is caught up before it is given anything new.
        self._history_size = history
        self._history: dict[str, list[Event]] = {}

    def publish(self, type: str, session_id: str,
                data: Optional[dict] = None) -> Event:
        """Publish an event to a session, and return it.

        The caller does not pass an id or a timestamp: the bus owns
        both, because the order has to be consistent across every
        publisher of the same bus. The returned event is the same
        object the subscribers receive, so a caller can log exactly
        what it published.
        """
        with self._lock:
            event = Event(
                id=str(self._next_id).zfill(ID_WIDTH),
                type=type,
                session_id=session_id,
                # A copy: the caller is free to reuse its dictionary,
                # and a later mutation must not rewrite history for a
                # subscriber that has not read the event yet.
                data=dict(data) if data is not None else {},
                ts=time.time(),
            )
            self._next_id += 1
            remembered = self._history.setdefault(session_id, [])
            remembered.append(event)
            if len(remembered) > self._history_size:
                del remembered[:-self._history_size]
            queues = list(self._subscribers.get(session_id, ()))

        # Outside the lock. A subscriber that is slow must never be
        # able to stall the publisher, and putting is the only place
        # where a consumer can slow anything down.
        for q in queues:
            q.put_nowait(event)
        return event

    def subscribe(self, session_id: str) -> queue.Queue:
        """Register a new subscriber for a session and return its queue.

        The queue arrives PRE-FILLED with the session's recent events.

        A client that POSTS a job and then opens the stream would
        otherwise miss everything published in between - and the order
        the API documents invites exactly that. So a late subscriber is
        caught up first, and then continues with the live feed.
        """
        q = _SubscriberQueue()
        with self._lock:
            for event in self._history.get(session_id, ()):
                q.put_nowait(event)
            self._subscribers.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(self, session_id: str) -> None:
        """Drop every subscriber of a session and close their queues.

        Closing is the point: a stream that has ended must say so to the
        reader, and a reader blocked on ``get()`` must be woken
        rather than left hanging on a queue nobody will ever fill.

        This drops the WHOLE session, which is not what a single
        disconnected client wants — see ``unsubscribe_queue``.
        """
        with self._lock:
            queues = self._subscribers.pop(session_id, [])
        # Outside the lock: closing wakes readers, and a woken reader
        # may well call back into the bus.
        for q in queues:
            q.close()

    def unsubscribe_queue(self, subscriber: queue.Queue) -> None:
        """Drop ONE subscriber and close its queue.

        A session may have several subscribers — a browser tab and a
        script watching the same job — and one of them going away must
        not take the others with it. Dropping the whole session on the
        first disconnect would kill the second watcher, which is the
        opposite of what a session is for.
        """
        with self._lock:
            for session_id, queues in list(self._subscribers.items()):
                if any(q is subscriber for q in queues):
                    # Rebuilt rather than removed in place: the registry
                    # holds the private queue type, and the caller only
                    # ever holds the protocol type.
                    self._subscribers[session_id] = [
                        q for q in queues if q is not subscriber]
                    if not self._subscribers[session_id]:
                        del self._subscribers[session_id]
                    break
        close = getattr(subscriber, "close", None)
        if close is not None:
            close()
