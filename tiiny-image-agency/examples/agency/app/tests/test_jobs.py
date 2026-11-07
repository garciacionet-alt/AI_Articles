"""Tests for the job store: the app's memory of what it was asked to do.

The store is the seam between a request and the minute it takes to answer
it, so the tests are mostly about survival: a job created now must still be
there after an update, and its payload must come back exactly as it went
in.
"""
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from tis.jobs import Job, JobStore

JOB_ID = re.compile(r"^job_[0-9a-f]{16}$")

NESTED_PAYLOAD = {
    "requirements": {
        "artifact": "icon",
        "alpha": "required",
        "hard": ["native_alpha", "solid_fill"],
    },
    "alternatives": [
        {"id": "Tongyi-MAI/Z-Image-Turbo", "npu_usage": 26},
        {"id": "Qwen/Qwen-Image-2.1", "npu_usage": 62},
    ],
    "swap_plan": {"evict": [], "load": "Qwen/Qwen-Image-2.1"},
    "attempts": 3,
}


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def test_a_created_job_has_the_store_set_fields(store: JobStore):
    job = store.create("sess-1", "generate", "a fox icon")

    assert isinstance(job, Job)
    assert job.session_id == "sess-1"
    assert job.kind == "generate"
    assert job.request == "a fox icon"
    assert job.status == "queued"
    assert job.error is None
    assert job.payload == {}


def test_the_job_id_has_the_expected_shape(store: JobStore):
    job = store.create("sess-1", "generate", "a fox icon")

    assert JOB_ID.match(job.id), job.id
    assert job.id.startswith("job_")
    assert len(job.id) == len("job_") + 16


def test_a_job_survives_create_get_update_list_and_delete(store: JobStore):
    created = store.create("sess-1", "generate", "a fox icon")

    fetched = store.get(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.request == "a fox icon"
    assert fetched.status == "queued"

    updated = store.update(created.id, status="running")
    assert updated.status == "running"
    assert updated.id == created.id

    assert store.get(created.id).status == "running"
    assert [job.id for job in store.list()] == [created.id]

    assert store.delete(created.id) is True
    assert store.get(created.id) is None
    assert store.list() == []


def test_the_payload_round_trips_including_nested_dicts_and_lists(
        store: JobStore):
    created = store.create("sess-1", "generate", "a fox icon",
                            payload=NESTED_PAYLOAD)

    fetched = store.get(created.id)
    assert fetched is not None
    assert fetched.payload == NESTED_PAYLOAD
    assert fetched.payload["requirements"]["hard"] == ["native_alpha",
                                                       "solid_fill"]
    assert fetched.payload["alternatives"][1]["id"] == "Qwen/Qwen-Image-2.1"


def test_a_job_created_without_a_payload_has_an_empty_payload(store: JobStore):
    created = store.create("sess-1", "generate", "a fox icon")

    fetched = store.get(created.id)
    assert fetched is not None
    assert fetched.payload == {}


def test_the_payload_can_be_replaced_by_an_update(store: JobStore):
    created = store.create("sess-1", "generate", "a fox icon",
                            payload={"a": 1})

    updated = store.update(created.id, payload={"b": [1, 2, 3]})

    assert updated.payload == {"b": [1, 2, 3]}
    assert store.get(created.id).payload == {"b": [1, 2, 3]}


def test_update_raises_key_error_for_an_unknown_job(store: JobStore):
    with pytest.raises(KeyError):
        store.update("job_0000000000000000", status="running")


def test_delete_returns_false_for_an_unknown_job(store: JobStore):
    assert store.delete("job_0000000000000000") is False


def test_get_returns_none_for_an_unknown_job(store: JobStore):
    assert store.get("job_0000000000000000") is None


def test_list_with_a_session_id_returns_only_that_sessions_jobs(
        store: JobStore):
    mine = store.create("sess-mine", "generate", "a fox icon")
    theirs = store.create("sess-theirs", "generate", "a cat icon")
    time.sleep(0.002)
    mine_again = store.create("sess-mine", "iterate", "make it sharper")

    listed = store.list(session_id="sess-mine")

    assert [job.id for job in listed] == [mine_again.id, mine.id]
    assert theirs.id not in [job.id for job in listed]


def test_list_without_a_session_id_returns_every_job(store: JobStore):
    first = store.create("sess-1", "generate", "a fox icon")
    time.sleep(0.002)
    second = store.create("sess-2", "generate", "a cat icon")

    assert {job.id for job in store.list()} == {first.id, second.id}


def test_list_returns_the_newest_first(store: JobStore):
    first = store.create("sess-1", "generate", "first")
    time.sleep(0.002)
    second = store.create("sess-1", "generate", "second")
    time.sleep(0.002)
    third = store.create("sess-1", "generate", "third")

    assert [job.id for job in store.list()] == [third.id, second.id, first.id]


def test_list_honours_the_limit(store: JobStore):
    for index in range(5):
        store.create("sess-1", "generate", f"request {index}")
        time.sleep(0.002)

    assert len(store.list(limit=2)) == 2
    assert len(store.list()) == 5


def test_the_store_sets_the_timestamps_not_the_caller(store: JobStore):
    before = time.time()
    created = store.create("sess-1", "generate", "a fox icon")
    after = time.time()

    assert before <= created.created_at <= after
    assert created.updated_at == created.created_at


def test_an_update_moves_updated_at_forward(store: JobStore):
    created = store.create("sess-1", "generate", "a fox icon")
    time.sleep(0.002)

    updated = store.update(created.id, status="running")

    assert updated.updated_at > created.updated_at
    assert updated.created_at == created.created_at
    assert store.get(created.id).updated_at == updated.updated_at


def test_a_caller_cannot_move_the_timestamps(store: JobStore):
    created = store.create("sess-1", "generate", "a fox icon")

    updated = store.update(created.id, created_at=0.0, updated_at=0.0)

    assert updated.created_at == created.created_at
    assert updated.updated_at > created.created_at


def test_an_update_can_set_the_status_and_the_error(store: JobStore):
    created = store.create("sess-1", "generate", "a fox icon")

    updated = store.update(created.id, status="failed",
                            error="the appliance was unreachable")

    assert updated.status == "failed"
    assert updated.error == "the appliance was unreachable"
    assert store.get(created.id).error == "the appliance was unreachable"


def test_the_table_is_created_on_first_use(tmp_path: Path):
    path = tmp_path / "nested" / "jobs.db"
    JobStore(path)

    assert path.exists()
    with sqlite3.connect(path) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
    assert "jobs" in tables


def test_the_payload_is_stored_as_json_text(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    created = store.create("sess-1", "generate", "a fox icon",
                            payload={"a": 1})

    with sqlite3.connect(tmp_path / "jobs.db") as connection:
        raw = connection.execute(
            "SELECT payload FROM jobs WHERE id = ?", (created.id,)
        ).fetchone()[0]

    assert json.loads(raw) == {"a": 1}


def test_the_store_is_safe_to_use_from_several_threads(store: JobStore):
    created: list[str] = []
    errors: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(20):
                job = store.create("sess-1", "generate", "a fox icon")
                created.append(job.id)
                store.get(job.id)
                store.list()
        except BaseException as exc:  # pragma: no cover - only on a failure
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(store.list(limit=200)) == 80
    assert len(set(created)) == 80
