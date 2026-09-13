"""spec 009-model-routing (keel-cloud `canon/designs/model-routing-design.md` §5, §6).

One rule: the job's `request_payload["model"][<host_key>]` goes to the CLI as that host's model
flag; nothing else names a model anywhere in this runtime. When the CLI refuses the named model by
a **measured** marker (2026-09-13, `tests/fixtures/<host>/`), the job is run once more unpinned
and the completion says so. Every host executor carries the same five report attributes, and the
poller turns them into the `execution` object `/complete` and `/fail` carry.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from keel_runtime import executor as executor_module
from keel_runtime.cloud_client import CloudClient
from keel_runtime.executor import (
    CLAUDE_MODEL_REFUSAL_MARKERS,
    CODEX_MODEL_REFUSAL_MARKERS,
    COPILOT_MODEL_REFUSAL_MARKERS,
    ExecutorAuthFailure,
    ExecutorUnavailable,
    InferenceRequest,
    _render_copilot_prompt,
    _render_prompt,
)
from keel_runtime.poller import _execution_report, _handle_job, _model_for

from . import test_codex_executor as codex_tests
from . import test_copilot_executor as copilot_tests
from . import test_executor as claude_tests

_FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(host: str, name: str) -> str:
    return (_FIXTURES / host / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------- the poller's one rule (§6)


class _FakeHostExecutor:
    """A host executor as the poller sees it: `host_key`, the five report attributes, and an
    `execute` that records the request it was handed."""

    host_key = "codex"
    host_version = "codex-cli 0.154.0"

    def __init__(self, response=None, exception=None, model_used=None, retried=False):
        self._response = response
        self._exception = exception
        self.requests = []
        self.last_model_requested = None
        self.last_model_used = model_used
        self.last_retried_unpinned = retried
        self.last_envelope = {"executor": "codex"}
        self.last_request_sections = None
        self.last_events = None

    def execute(self, request):
        self.requests.append(request)
        self.last_model_requested = request.model
        if self._exception is not None:
            raise self._exception
        return self._response


class _FakeClient:
    """Accepts the optional `execution` keyword, as the real client does since spec 009."""

    def __init__(self):
        self.completed = []
        self.failed = []

    def complete_job(self, job_id, access_token, response, execution=None):
        self.completed.append((job_id, response, execution))
        return {}

    def fail_job(self, job_id, access_token, code, message, execution=None):
        self.failed.append((job_id, code, message, execution))
        return {}


_CONTRACT = {
    "allowed_outcomes": ["COMPLETED"],
    "completed_result_schema": {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": "string"}},
    },
}


def _job(model=None, job_id="job-1"):
    payload = {
        "instruction": "do it",
        "context": {},
        "interaction_history": [],
        "input": {"content": "hi"},
        "response_contract": _CONTRACT,
    }
    if model is not None:
        payload["model"] = model
    return {
        "job_id": job_id,
        "interaction_id": "interaction-1",
        "turn_number": 1,
        "request_payload": payload,
    }


class ModelForTest(unittest.TestCase):
    """`_model_for`: this host's entry, or nothing. Never another host's, never a non-string."""

    def test_this_hosts_entry_is_read_and_the_others_ignored(self):
        payload = _job(model={"claude": "sonnet", "copilot": "gpt-5.6-luna", "codex": "gpt-5.6-terra"})
        self.assertEqual(_model_for(_FakeHostExecutor(), payload["request_payload"]), "gpt-5.6-terra")

    def test_a_job_without_the_key_or_without_this_host_means_no_flag(self):
        cases = {
            "no key (an older cloud)": _job(),
            "no entry for this host (an unmeasured host or tier)": _job(model={"claude": "sonnet"}),
            "not a map": _job(model="gpt-5.6-terra"),
            "not a string": _job(model={"codex": 7}),
            "an empty string": _job(model={"codex": "  "}),
        }
        for label, job in cases.items():
            with self.subTest(label):
                self.assertIsNone(_model_for(_FakeHostExecutor(), job["request_payload"]))

    def test_an_executor_without_a_host_is_never_pinned(self):
        payload = _job(model={"codex": "gpt-5.6-terra"})["request_payload"]
        self.assertIsNone(_model_for(SimpleNamespace(), payload))
        self.assertIsNone(_execution_report(SimpleNamespace()))


class HandleJobReportsExecutionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config = SimpleNamespace(home=Path(self._tmp.name))
        self.state = SimpleNamespace(access_token="tok")
        self.client = _FakeClient()

    def test_the_request_carries_the_hosts_model_and_complete_carries_the_report(self):
        executor = _FakeHostExecutor(
            response={"outcome": "COMPLETED", "result": {"x": "ok"}}, model_used="gpt-5.6-terra"
        )
        _handle_job(self.client, self.state, executor,
                    _job(model={"codex": "gpt-5.6-terra", "claude": "sonnet"}), self.config)
        self.assertEqual(executor.requests[0].model, "gpt-5.6-terra")
        (job_id, response, execution), = self.client.completed
        self.assertEqual(response, {"outcome": "COMPLETED", "result": {"x": "ok"}})
        self.assertEqual(execution, {
            "host": "codex",
            "host_version": "codex-cli 0.154.0",
            "model_requested": "gpt-5.6-terra",
            "model_used": "gpt-5.6-terra",
            "retried_unpinned": False,
        })
        written = json.loads((self.config.home / "jobs" / "job-1" / "execution.json").read_text())
        self.assertEqual(written, execution)

    def test_a_failed_job_carries_the_report_too(self):
        executor = _FakeHostExecutor(exception=ExecutorUnavailable("boom"), retried=True)
        _handle_job(self.client, self.state, executor, _job(model={"codex": "gpt-5.5-mini"}), self.config)
        (job_id, code, message, execution), = self.client.failed
        self.assertEqual(code, "LLM_UNAVAILABLE")
        self.assertEqual(execution["model_requested"], "gpt-5.5-mini")
        self.assertIsNone(execution["model_used"])
        self.assertTrue(execution["retried_unpinned"])

    def test_a_job_with_no_model_reports_none_requested(self):
        executor = _FakeHostExecutor(response={"outcome": "COMPLETED", "result": {"x": "ok"}})
        _handle_job(self.client, self.state, executor, _job(), self.config)
        self.assertIsNone(executor.requests[0].model)
        self.assertIsNone(self.client.completed[0][2]["model_requested"])


class CloudClientBodiesTest(unittest.TestCase):
    """`execution` is additive: present in the body only when given, so a scripted run's body
    is byte-identical to 0.4.0's."""

    def _capturing(self):
        client = CloudClient(base_url="http://example.invalid")
        seen = []

        def fake_request(method, path, body=None, access_token=None, timeout=None):
            seen.append((method, path, body))
            return {}

        client._request = fake_request
        return client, seen

    def test_complete_and_fail_carry_execution_only_when_given(self):
        client, seen = self._capturing()
        report = {"host": "claude", "host_version": "2.1.270 (Claude Code)",
                  "model_requested": "sonnet", "model_used": "claude-sonnet-5", "retried_unpinned": False}
        client.complete_job("j1", "tok", {"outcome": "COMPLETED"})
        client.complete_job("j2", "tok", {"outcome": "COMPLETED"}, execution=report)
        client.fail_job("j3", "tok", "LLM_UNAVAILABLE", "LLM_UNAVAILABLE: x")
        client.fail_job("j4", "tok", "LLM_UNAVAILABLE", "LLM_UNAVAILABLE: x", execution=report)
        self.assertEqual(seen[0][2], {"response": {"outcome": "COMPLETED"}})
        self.assertEqual(seen[1][2], {"response": {"outcome": "COMPLETED"}, "execution": report})
        self.assertEqual(seen[2][2], {"error_code": "LLM_UNAVAILABLE", "error_message": "LLM_UNAVAILABLE: x"})
        self.assertEqual(seen[3][2]["execution"], report)


# ------------------------------------------------------- the unpinned retry, per host (FR-006)


class CodexRefusalRetryTest(codex_tests._FakeCodexCase):
    """Measured 2026-09-13: a mini on a ChatGPT plan is refused with the API's 400 in an `error`
    + `turn.failed` pair (`unsupported-model-on-plan.jsonl`)."""

    def test_a_refused_model_is_retried_once_unpinned_and_reported(self):
        self._queue(
            {"stdout": _fixture("codex", "unsupported-model-on-plan.jsonl"),
             "stderr": _fixture("codex", "unsupported-model-on-plan.stderr"), "returncode": 1},
            {"stdout": _fixture("codex", "completed.jsonl"), "returncode": 0},
        )
        answer = self.executor.execute(codex_tests._request(model="gpt-5.5-mini"))
        self.assertEqual(answer["outcome"], "COMPLETED")
        records = self._records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["argv"][records[0]["argv"].index("-m") + 1], "gpt-5.5-mini")
        self.assertNotIn("-m", records[1]["argv"])
        self.assertEqual(self.executor.last_model_requested, "gpt-5.5-mini")
        self.assertIsNone(self.executor.last_model_used, "this CLI names no model in its stream")
        self.assertTrue(self.executor.last_retried_unpinned)
        # the refused pass stays in the log, ahead of the answering one
        self.assertEqual(self.executor.last_events[0]["type"], "thread.started")
        self.assertTrue(any(e.get("type") == "turn.failed" for e in self.executor.last_events))
        self.assertTrue(any(e.get("type") == "turn.completed" for e in self.executor.last_events))

    def test_the_api_key_refusal_is_retried_the_same_way(self):
        """Measured 2026-09-13 on an API-key sign-in: the 404 "does not exist or you do not have
        access to it", repeated through the reconnects (`unsupported-model-on-api-key.jsonl`)."""
        self._queue(
            {"stdout": _fixture("codex", "unsupported-model-on-api-key.jsonl"),
             "stderr": _fixture("codex", "unsupported-model-on-api-key.stderr"), "returncode": 1},
            {"stdout": _fixture("codex", "completed.jsonl"), "returncode": 0},
        )
        answer = self.executor.execute(codex_tests._request(model="gpt-5.5-mini"))
        self.assertEqual(answer["outcome"], "COMPLETED")
        self.assertEqual(len(self._records()), 2)
        self.assertNotIn("-m", self._records()[1]["argv"])
        self.assertTrue(self.executor.last_retried_unpinned)

    def test_an_unknown_name_is_refused_the_same_way(self):
        self._queue(
            {"stdout": _fixture("codex", "unknown-model.jsonl"), "returncode": 1},
            {"stdout": _fixture("codex", "completed.jsonl"), "returncode": 0},
        )
        self.executor.execute(codex_tests._request(model="not-a-model"))
        self.assertTrue(self.executor.last_retried_unpinned)
        self.assertEqual(len(self._records()), 2)

    def test_no_model_means_no_retry_the_failure_is_what_it_is(self):
        self._queue({"stdout": _fixture("codex", "unsupported-model-on-plan.jsonl"), "returncode": 1})
        with self.assertRaises(ExecutorUnavailable):
            self.executor.execute(codex_tests._request())
        self.assertEqual(len(self._records()), 1)
        self.assertFalse(self.executor.last_retried_unpinned)

    def test_a_different_failure_with_a_model_is_not_retried(self):
        self._queue({"stdout": _fixture("codex", "unauthenticated-no-credential.jsonl"),
                     "stderr": _fixture("codex", "unauthenticated-no-credential.stderr"), "returncode": 1})
        with self.assertRaises(ExecutorAuthFailure):
            self.executor.execute(codex_tests._request(model="gpt-5.6-terra"))
        self.assertEqual(len(self._records()), 1)
        self.assertFalse(self.executor.last_retried_unpinned)
        self.assertEqual(self.executor.last_model_requested, "gpt-5.6-terra")

    def test_the_second_pass_is_the_one_asserted_and_read(self):
        """A refused first pass and a tool-using second pass: the closed-shape check reads the
        pass that answered, and fails it."""
        self._queue(
            {"stdout": _fixture("codex", "unsupported-model-on-plan.jsonl"), "returncode": 1},
            {"stdout": _fixture("codex", "open-asked-to-run-a-command.jsonl"), "returncode": 0},
        )
        with self.assertRaises(ExecutorUnavailable):
            self.executor.execute(codex_tests._request(model="gpt-5.5-mini"))
        self.assertTrue(self.executor.last_retried_unpinned)


class CopilotRefusalRetryTest(copilot_tests._FakeCopilotCase):
    """Measured 2026-09-13 on 1.0.83: one stderr line, no JSONL (`unknown-model.stderr`)."""

    def test_a_refused_model_is_retried_once_unpinned_and_reported(self):
        self._queue(
            {"stdout": "", "stderr": _fixture("copilot", "unknown-model.stderr"), "returncode": 1},
            {"stdout": _fixture("copilot", "completed.jsonl"), "returncode": 0},
        )
        answer = self.executor.execute(copilot_tests._request(model="not-a-model"))
        self.assertEqual(answer["outcome"], "COMPLETED")
        records = self._records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["argv"][records[0]["argv"].index("--model") + 1], "not-a-model")
        self.assertNotIn("--model", records[1]["argv"])
        self.assertEqual(self.executor.last_model_requested, "not-a-model")
        self.assertTrue(self.executor.last_retried_unpinned)
        # this CLI names the model it ran (`chosenModel` in the recorded run), so it is reported
        self.assertEqual(self.executor.last_model_used, "gpt-5.6-luna")

    def test_the_reported_model_is_read_when_the_named_one_was_served(self):
        self._queue_stdout(_fixture("copilot", "completed.jsonl"))
        self.executor.execute(copilot_tests._request(model="gpt-5.6-luna"))
        self.assertFalse(self.executor.last_retried_unpinned)
        self.assertEqual(self.executor.last_model_used, "gpt-5.6-luna")

    def test_no_model_means_no_retry(self):
        self._queue({"stdout": "", "stderr": _fixture("copilot", "unknown-model.stderr"), "returncode": 1})
        with self.assertRaises(ExecutorUnavailable):
            self.executor.execute(copilot_tests._request())
        self.assertEqual(len(self._records()), 1)
        self.assertFalse(self.executor.last_retried_unpinned)

    def test_the_session_error_lookalike_is_not_a_model_refusal(self):
        """design §5.4: the CAPIError 400 "The requested model is not supported" an invalid
        token once produced names no flag; it stays an unrecognised session error, unretried."""
        stream = json.dumps({"type": "session.error", "data": {
            "message": "CAPIError: 400 The requested model is not supported."}}) + "\n"
        self._queue({"stdout": stream, "returncode": 0})
        with self.assertRaises(ExecutorUnavailable):
            self.executor.execute(copilot_tests._request(model="gpt-5.6-luna"))
        self.assertEqual(len(self._records()), 1)
        self.assertFalse(self.executor.last_retried_unpinned)


class ClaudeRefusalRetryTest(claude_tests._ExecutorTestBase):
    """Measured 2026-09-13 on Claude Code 2.1.270: `is_error` with `terminal_reason: api_error`
    and the "issue with the selected model" text (`unknown-model.jsonl`)."""

    def _good_stream(self):
        init = {"type": "system", "subtype": "init", "model": "claude-sonnet-5-20260601"}
        return claude_tests._stream(
            init, self._result_event(structured_output={"outcome": "COMPLETED", "result": {"x": "ok"}})
        )

    def test_a_refused_model_is_retried_once_unpinned_and_reported(self):
        self._set_raw_responses([
            {"stdout": _fixture("claude", "unknown-model.jsonl"),
             "stderr": _fixture("claude", "unknown-model.stderr"), "returncode": 1},
            {"stdout": self._good_stream(), "stderr": "", "returncode": 0},
        ])
        answer = self.executor.execute(claude_tests._request(model="not-a-model"))
        self.assertEqual(answer, {"outcome": "COMPLETED", "result": {"x": "ok"}})
        records = self._records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["argv"][records[0]["argv"].index("--model") + 1], "not-a-model")
        self.assertNotIn("--model", records[1]["argv"])
        self.assertEqual(self.executor.last_model_requested, "not-a-model")
        self.assertTrue(self.executor.last_retried_unpinned)
        # the model the answering pass's init event names, never the refused pass's `<synthetic>`
        self.assertEqual(self.executor.last_model_used, "claude-sonnet-5-20260601")

    def test_an_alias_comes_back_as_the_name_the_cli_resolved(self):
        self._set_raw_responses([{"stdout": self._good_stream(), "stderr": "", "returncode": 0}])
        self.executor.execute(claude_tests._request(model="sonnet"))
        self.assertFalse(self.executor.last_retried_unpinned)
        self.assertEqual(self.executor.last_model_requested, "sonnet")
        self.assertEqual(self.executor.last_model_used, "claude-sonnet-5-20260601")

    def test_no_model_means_no_retry(self):
        self._set_raw_responses([{"stdout": _fixture("claude", "unknown-model.jsonl"),
                                  "stderr": _fixture("claude", "unknown-model.stderr"), "returncode": 1}])
        with self.assertRaises(ExecutorUnavailable):
            self.executor.execute(claude_tests._request())
        self.assertEqual(len(self._records()), 1)
        self.assertFalse(self.executor.last_retried_unpinned)

    def test_a_different_error_with_a_model_is_not_retried(self):
        self._set_stream(self._result_event(is_error=True, result="something else went wrong"))
        with self.assertRaises(ExecutorUnavailable):
            self.executor.execute(claude_tests._request(model="sonnet"))
        self.assertEqual(len(self._records()), 1)
        self.assertFalse(self.executor.last_retried_unpinned)


class TheMarkersAreTheMeasuredOnesTest(unittest.TestCase):
    """A marker nobody recorded is not a marker: each constant is a substring of its fixture."""

    def test_each_marker_is_in_its_recording(self):
        codex = (_fixture("codex", "unsupported-model-on-plan.jsonl")
                 + _fixture("codex", "unsupported-model-on-api-key.jsonl")).lower()
        copilot = _fixture("copilot", "unknown-model.stderr").lower()
        claude = (_fixture("claude", "unknown-model.jsonl") + _fixture("claude", "unknown-model.stderr")).lower()
        for marker in CODEX_MODEL_REFUSAL_MARKERS:
            self.assertIn(marker, codex)
        # and each Codex recording carries one of the two -- a plan refusal and an API-key one
        for name in ("unsupported-model-on-plan.jsonl", "unsupported-model-on-api-key.jsonl"):
            text = _fixture("codex", name).lower()
            self.assertTrue(any(marker in text for marker in CODEX_MODEL_REFUSAL_MARKERS), name)
        for marker in COPILOT_MODEL_REFUSAL_MARKERS:
            self.assertIn(marker, copilot)
        for marker in CLAUDE_MODEL_REFUSAL_MARKERS:
            self.assertIn(marker, claude)


# ------------------------------------------------ the DRIFT #67 sentences in the RESPONSE section


class TheResponseSectionNamesTheTwoRulesTest(unittest.TestCase):
    """keel-e2e-eval DRIFT #67: Copilot's run of record missed on one invented unit and the word
    "proxy". The Copilot-shaped prompt (Codex reads it too) now repeats both rules in RESPONSE; the
    Claude-shaped prompt, which did not miss, is unchanged."""

    def setUp(self):
        request = claude_tests._request()
        self.sections = executor_module._prompt_sections(request)
        self.schema = executor_module._build_envelope_schema({})

    def test_the_copilot_shaped_prompt_carries_the_word_and_the_units(self):
        prompt = _render_copilot_prompt(self.sections, self.schema)
        response = prompt[prompt.index("RESPONSE"):prompt.index("TASK")]
        self.assertIn('never the word "proxy"', response)
        for unit in ("minutes", "hours", "days", "weeks", "months", "years",
                     "working-hours", "working-days", "working-weeks"):
            self.assertIn(unit, response)
        self.assertIn("percent", response)
        self.assertIn("ISO", response)

    def test_the_claude_shaped_prompt_is_unchanged(self):
        prompt = _render_prompt(self.sections)
        self.assertNotIn("proxy", prompt)
        self.assertNotIn("working-weeks", prompt)
        self.assertNotIn("RESPONSE", prompt)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
