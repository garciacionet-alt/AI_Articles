"""The job store: the record of what the app was asked to do and what came of it.

A generation takes a minute on a single shared appliance, so the request
and its result cannot live in the same call. The job store is the seam
between them: a job is created when the request is accepted, moved through
its states while the appliance works, and read afterwards by the API, by
the SSE bus and by anything else that wants to know what happened to it.

SQLite rather than a file of JSON lines, because the job list is queried
by session and ordered by time every time the work surface polls, and
because a half-written line at the end of an append-only file is a job
that cannot be listed at all.

ONE CONNECTION, ONE LOCK
------------------------
The SSE bus and the HTTP handler touch the store from different threads.
SQLite serialises its own writes, but that is not the same guarantee as
"a reader never sees half of a write", so every read and every write here
takes the same lock.

THE STORE OWNS THE TIMESTAMPS
------------------------------
A job's age is evidence about how long the appliance took. A caller that
could set ``updated_at`` could lie about that, so the timestamps are not
among the fields a caller may change.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

#: The states a job moves through. A job is queued when it is accepted,
#: running while the appliance works, and then it either succeeded or
#: failed — and it never goes back.
JOB_STATUSES: tuple[str, ...] = ("queued", "running", "succeeded", "failed")

#: The fields a caller may change. The id identifies the job, and the
#: timestamps are the store's own — a job's age is evidence about how
#: long the appliance took, and a caller that could set it could lie.
#: The two are treated differently on purpose: the id is REJECTED,
#: because it is the key the job is found by, while the timestamps are
#: IGNORED, so a caller that round-trips a whole Job does not have to
#: remember to strip the store's own fields before handing them back.
MUTABLE_FIELDS: frozenset[str] = frozenset({
    "session_id", "kind", "request", "status", "payload", "error",
})

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    request    TEXT NOT NULL,
    status     TEXT NOT NULL,
    payload    TEXT NOT NULL,
    error      TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS jobs_by_session
    ON jobs (session_id, created_at DESC);
"""


@dataclass(frozen=True)
class Job:
    """One request's worth of work, as the store sees it."""

    id: str
    session_id: str
    kind: str
    request: str
    status: str
    payload: dict
    error: str | None
    created_at: float
    updated_at: float


class JobStore:
    """The job log, on disk, safe to use from several threads."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # One connection for the life of the store: a second connection
        # would be a second writer, and SQLite would rather it did not.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    # -- the schema -------------------------------------------------------

    def _create_schema(self) -> None:
        """Create the table on first use.

        ``IF NOT EXISTS`` because the store is opened on every start of
        the app and the jobs must survive it.
        """
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # -- writing ----------------------------------------------------------

    def create(self, session_id: str, kind: str, request: str,
               payload: dict | None = None) -> Job:
        """Record a new job, queued.

        The payload is copied on the way in, so a caller that keeps
        mutating its own dict does not change a job that is already
        written down.
        """
        now = time.time()
        job = Job(
            id=_new_job_id(),
            session_id=session_id,
            kind=kind,
            request=request,
            status="queued",
            payload=dict(payload or {}),
            error=None,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (id, session_id, kind, request, status,"
                " payload, error, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job.id, job.session_id, job.kind, job.request, job.status,
                 json.dumps(job.payload), job.error, job.created_at,
                 job.updated_at),
            )
            self._conn.commit()
        return job

    def update(self, job_id: str, **changes) -> Job:
        """Change a job and return it as it now stands.

        Raises ``KeyError`` for a job that is not there: a caller that
        is updating a job expects one to exist, and silently creating
        it would hide the mistake.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)

            job = _row_to_job(row)
            for name, value in changes.items():
                if name in ("created_at", "updated_at"):
                    # The store's business, not the caller's: ignored,
                    # so a caller that round-trips a whole Job does not
                    # have to strip the store's own fields first.
                    continue
                if name not in MUTABLE_FIELDS:
                    raise ValueError(
                        f"job field {name!r} cannot be changed; the "
                        f"changeable fields are {sorted(MUTABLE_FIELDS)}"
                    )
                if name == "status" and value not in JOB_STATUSES:
                    raise ValueError(
                        f"unknown job status {value!r}; the statuses are "
                        f"{list(JOB_STATUSES)}"
                    )
                if name == "payload":
                    value = dict(value or {})
                elif name == "error":
                    value = None if value is None else str(value)
                else:
                    value = str(value)
                job = replace(job, **{name: value})

            job = replace(job, updated_at=time.time())
            self._conn.execute(
                "UPDATE jobs SET session_id = ?, kind = ?, request = ?,"
                " status = ?, payload = ?, error = ?, updated_at = ?"
                " WHERE id = ?",
                (job.session_id, job.kind, job.request, job.status,
                 json.dumps(job.payload), job.error, job.updated_at, job.id),
            )
            self._conn.commit()
        return job

    def delete(self, job_id: str) -> bool:
        """Forget a job. True if it was there, False if it was not."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    # -- reading ----------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        """The job with this id, or None if there is no such job."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_job(row)

    def list(self, session_id: str | None = None, limit: int = 50) -> list[Job]:
        """The jobs, newest first.

        Newest first because that is how a person reads a list of work:
        the thing they asked about a moment ago is at the top. The id
        breaks ties, so two jobs created in the same instant still come
        back in a fixed order.
        """
        limit = max(0, int(limit))
        with self._lock:
            if session_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC, id DESC"
                    " LIMIT ?", (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE session_id = ?"
                    " ORDER BY created_at DESC, id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
        return [_row_to_job(row) for row in rows]

    # -- housekeeping -----------------------------------------------------

    def close(self) -> None:
        """Close the database file."""
        with self._lock:
            self._conn.close()


def _new_job_id() -> str:
    """A job id: the prefix and sixteen hex characters of a uuid4."""
    return f"job_{uuid.uuid4().hex[:16]}"


def _row_to_job(row: sqlite3.Row) -> Job:
    """Rebuild a job from its row.

    A payload that will not parse reads as empty rather than taking the
    list down: a job whose payload is unreadable is still a job, and the
    rest of its fields are the ones a person needs.
    """
    try:
        payload = json.loads(row["payload"]) if row["payload"] else {}
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return Job(
        id=row["id"],
        session_id=row["session_id"],
        kind=row["kind"],
        request=row["request"],
        status=row["status"],
        payload=payload,
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
