"""Tests for `keel_runtime.poller` (spec 002-words-are-words FR-005, FR-008).

Covers: the per-job `envelope.json`/`request.json` logs (written when the executor
exposes `last_envelope`/`last_request_sections`, a no-op for one that doesn't, e.g. the
scripted/stub executors), the `/fail` message shape (`<code>: <=200 chars>`, never
model output), no-retry on failure, and pruning job directories to the newest 50.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from keel_runtime.executor import ExecutorUnavailable
from keel_runtime.poller import JOB_DIR_RETENTION, _handle_job, _prune_job_dirs


class _FakeClient:
    def __init__(self):
        self.completed = []
        self.failed = []

    def complete_job(self, job_id, access_token, response):
        self.completed.append((job_id, access_token, response))
        return {}

    def fail_job(self, job_id, access_token, code, message):
        self.failed.append((job_id, access_token, code, message))
        return {}


class _FakeExecutor:
    """A stand-in for either ClaudeCodeExecutor (exposes the two log attributes) or
    the scripted/stub executors (expose neither).
    """

    def __init__(self, response=None, exception=None, last_envelope=None,
                 last_request_sections=None, expose_logs=True):
        self._response = response
        self._exception = exception
        if expose_logs:
            self.last_envelope = last_envelope
            self.last_request_sections = last_request_sections

    def execute(self, request):
        if self._exception is not None:
            raise self._exception
        return self._response


_CONTRACT = {
    "allowed_outcomes": ["COMPLETED"],
    "completed_result_schema": {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": "string"}},
    },
}


def _job(job_id="job-1"):
    return {
        "job_id": job_id,
        "interaction_id": "interaction-1",
        "turn_number": 1,
        "request_payload": {
            "instruction": "do it",
            "context": {},
            "interaction_history": [],
            "input": {"content": "hi"},
            "response_contract": _CONTRACT,
        },
    }


class HandleJobLoggingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = SimpleNamespace(home=Path(self._tmp.name))
        self.state = SimpleNamespace(access_token="tok")
        self.client = _FakeClient()

    def tearDown(self):
        self._tmp.cleanup()

    def _job_dir(self, job_id="job-1"):
        return self.config.home / "jobs" / job_id

    def test_writes_envelope_and_request_json_on_success(self):
        envelope = {"is_error": False, "structured_output": {"outcome": "COMPLETED", "result": {"x": "ok"}}}
        sections = {"nonce": "abc123", "task": "do it"}
        executor = _FakeExecutor(
            response={"outcome": "COMPLETED", "result": {"x": "ok"}},
            last_envelope=envelope,
            last_request_sections=sections,
        )
        _handle_job(self.client, self.state, executor, _job(), self.config)

        job_dir = self._job_dir()
        self.assertEqual(json.loads((job_dir / "envelope.json").read_text()), envelope)
        self.assertEqual(json.loads((job_dir / "request.json").read_text()), sections)
        self.assertEqual(len(self.client.completed), 1)
        self.assertEqual(len(self.client.failed), 0)

    def test_writes_envelope_and_request_json_on_failure(self):
        envelope = {"is_error": True, "result": "budget exceeded"}
        sections = {"nonce": "def456", "task": "do it"}
        executor = _FakeExecutor(
            exception=ExecutorUnavailable("budget exceeded"),
            last_envelope=envelope,
            last_request_sections=sections,
        )
        _handle_job(self.client, self.state, executor, _job(), self.config)

        job_dir = self._job_dir()
        self.assertEqual(json.loads((job_dir / "envelope.json").read_text()), envelope)
        self.assertEqual(json.loads((job_dir / "request.json").read_text()), sections)

    def test_no_files_written_when_executor_exposes_no_logs(self):
        # The scripted and stub executors: no last_envelope/last_request_sections at
        # all -- this must stay a complete no-op for them (spec: they are untouched).
        executor = _FakeExecutor(
            response={"outcome": "COMPLETED", "result": {"x": "ok"}}, expose_logs=False
        )
        _handle_job(self.client, self.state, executor, _job(), self.config)
        self.assertFalse((self.config.home / "jobs").exists())


class FailMessageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = SimpleNamespace(home=Path(self._tmp.name))
        self.state = SimpleNamespace(access_token="tok")
        self.client = _FakeClient()

    def tearDown(self):
        self._tmp.cleanup()

    def test_message_is_code_colon_stderr_bounded_to_200_chars(self):
        long_stderr = "x" * 500
        executor = _FakeExecutor(exception=ExecutorUnavailable(long_stderr))
        _handle_job(self.client, self.state, executor, _job(), self.config)

        self.assertEqual(len(self.client.failed), 1)
        job_id, access_token, code, message = self.client.failed[0]
        self.assertEqual(code, "LLM_UNAVAILABLE")
        self.assertEqual(message, f"LLM_UNAVAILABLE: {'x' * 200}")

    def test_message_never_carries_model_output_only_the_exception_text(self):
        # The exception text is the executor's own diagnostic (CLI stderr / envelope
        # error string) -- never the job's `structured_output`.
        executor = _FakeExecutor(exception=ExecutorUnavailable("Not logged in."))
        _handle_job(self.client, self.state, executor, _job(), self.config)
        _, _, code, message = self.client.failed[0]
        self.assertEqual(message, "LLM_UNAVAILABLE: Not logged in.")

    def test_no_retry_on_failure(self):
        executor = _FakeExecutor(exception=ExecutorUnavailable("boom"))
        _handle_job(self.client, self.state, executor, _job(), self.config)
        self.assertEqual(len(self.client.failed), 1)
        self.assertEqual(len(self.client.completed), 0)


class PruneJobDirsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_jobs_dir_is_a_no_op(self):
        _prune_job_dirs(self.home)  # must not raise

    def test_keeps_newest_50_by_mtime(self):
        jobs_dir = self.home / "jobs"
        jobs_dir.mkdir()
        total = JOB_DIR_RETENTION + 5
        now = time.time()
        for index in range(total):
            job_dir = jobs_dir / f"job-{index:03d}"
            job_dir.mkdir()
            # oldest first: job-000 is oldest, job-{total-1} is newest.
            mtime = now - (total - index)
            os.utime(job_dir, (mtime, mtime))

        _prune_job_dirs(self.home)

        remaining = {entry.name for entry in jobs_dir.iterdir()}
        self.assertEqual(len(remaining), JOB_DIR_RETENTION)
        expected = {f"job-{index:03d}" for index in range(5, total)}
        self.assertEqual(remaining, expected)

    def test_fewer_than_the_cap_is_untouched(self):
        jobs_dir = self.home / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "job-a").mkdir()
        (jobs_dir / "job-b").mkdir()
        _prune_job_dirs(self.home)
        self.assertEqual({entry.name for entry in jobs_dir.iterdir()}, {"job-a", "job-b"})


if __name__ == "__main__":
    unittest.main()
