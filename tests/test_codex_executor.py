"""Tests for `CodexExecutor` (spec `008-codex-executor`; keel-skill-design.md decision 11's
pattern, invariants C-1..C-8 read for a third host).

**Every one of these runs against a recording, never against the real CLI.** The real calls were
made once, by hand, on 2026-09-12 against codex-cli 0.154.0 signed in with the founder's ChatGPT
plan, and their stdout and stderr are in `tests/fixtures/codex/` with `MANIFEST.json` saying how
each was produced. A fake `codex` goes first on `PATH` for the duration of each test and replays
one of those recordings, so the assertions below cost nothing and cannot drift with the founder's
account.

**These tests must pass with `jsonschema` absent** (R-2), for the reason `test_copilot_executor`
gives: on this host too, the runtime's own validator is the only thing between a model's prose
and `poller`.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from keel_runtime.executor import (
    CODEX_DISABLED_FEATURES,
    CODEX_EXEC_FLAGS,
    SYSTEM_PROMPT,
    CodexExecutor,
    ExecutorAuthFailure,
    ExecutorTimeout,
    ExecutorUnavailable,
    InferenceRequest,
    InvalidResponse,
)

from ._fake_cli import install_fake_cli

_FIXTURES = Path(__file__).parent / "fixtures" / "codex"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# The same fake the Copilot tests use: records argv, stdin, cwd and environment, replays one queued
# response per call (the last repeats), every stream UTF-8 explicitly.
_FAKE_CODEX_SOURCE = '''#!/usr/bin/env python3
import json
import os
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
records_path = os.path.join(here, "records.json")

if os.path.exists(records_path):
    with open(records_path) as handle:
        records = json.load(handle)
else:
    records = []

records.append({
    "argv": sys.argv[1:],
    "stdin": sys.stdin.buffer.read().decode("utf-8"),
    "cwd": os.getcwd(),
    "env": dict(os.environ),
})
with open(records_path, "w") as handle:
    json.dump(records, handle)

with open(os.path.join(here, "responses.json")) as handle:
    responses = json.load(handle)

response = responses[min(len(records) - 1, len(responses) - 1)]
if response.get("sleep"):
    time.sleep(response["sleep"])
sys.stdout.buffer.write(response.get("stdout", "").encode("utf-8"))
sys.stderr.buffer.write(response.get("stderr", "").encode("utf-8"))
sys.exit(response.get("returncode", 0))
'''


_CONTRACT_COMPLETED = {
    "allowed_outcomes": ["COMPLETED", "NEEDS_INPUT"],
    "completed_result_schema": {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string", "maxLength": 400}},
    },
}


def _request(
    instruction="Summarise the founder text below in one sentence.",
    content="Independent restaurant managers lose hours each week reconciling deliveries.",
    response_contract=None,
    job_id="job-1",
    model=None,
):
    return InferenceRequest(
        job_id=job_id,
        interaction_id="interaction-1",
        turn_number=1,
        request_payload={
            "instruction": instruction,
            "context": {},
            "interaction_history": [],
            "input": {"content": content},
            "response_contract": response_contract or _CONTRACT_COMPLETED,
        },
        model=model,
    )


class _FakeCodexCase(unittest.TestCase):
    """Puts a fake `codex` first on `PATH` and gives each test a fresh `$KEEL_HOME`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.bin_dir = root / "bin"
        self.bin_dir.mkdir()
        install_fake_cli(self.bin_dir, "codex", _FAKE_CODEX_SOURCE)

        self.home = root / "keel-home"
        self.home.mkdir()

        self._old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self.bin_dir) + os.pathsep + self._old_path
        self.addCleanup(self._restore_path)
        self.addCleanup(self._tmp.cleanup)

        self.executor = CodexExecutor(home=self.home, timeout_seconds=30.0)

    def _restore_path(self):
        os.environ["PATH"] = self._old_path

    def _queue(self, *responses):
        (self.bin_dir / "responses.json").write_text(json.dumps(list(responses)), encoding="utf-8")

    def _queue_stdout(self, *stdouts, returncode=0):
        self._queue(*[{"stdout": text, "returncode": returncode} for text in stdouts])

    def _records(self) -> list:
        return json.loads((self.bin_dir / "records.json").read_text(encoding="utf-8"))

    def _record(self, index=0) -> dict:
        return self._records()[index]


# ---------------------------------------------------------------------- the recorded runs


class TheRecordedCompletedRunTest(_FakeCodexCase):
    """`completed.jsonl` -- a verbatim recording of a real closed-shape run that answered."""

    def test_the_answer_is_the_agent_message_parsed_and_validated(self):
        self._queue_stdout(_fixture("completed.jsonl"))
        answer = self.executor.execute(_request())
        self.assertEqual(answer["outcome"], "COMPLETED")
        self.assertEqual(
            answer["result"]["summary"],
            "Independent restaurant managers spend hours each week matching deliveries to invoices.",
        )

    def test_the_envelope_reports_turns_and_tokens_and_never_a_dollar_figure(self):
        """C-7: Codex reports tokens against a plan. `total_cost_usd` is absent, not zero."""
        self._queue_stdout(_fixture("completed.jsonl"))
        self.executor.execute(_request())
        envelope = self.executor.last_envelope
        self.assertEqual(envelope["executor"], "codex")
        self.assertEqual(envelope["num_turns"], 1)
        self.assertEqual(envelope["tokens"]["output_tokens"], 35)
        self.assertEqual(envelope["exit_code"], 0)
        self.assertNotIn("total_cost_usd", envelope)
        self.assertNotIn("premium_requests", envelope)
        self.assertIsNone(self.executor.last_schema_error)

    def test_last_events_and_last_request_sections_are_exposed_for_the_poller(self):
        self._queue_stdout(_fixture("completed.jsonl"))
        self.executor.execute(_request())
        self.assertTrue(any(e.get("type") == "turn.completed" for e in self.executor.last_events))
        self.assertIn("nonce", self.executor.last_request_sections)


class TheRecordedRefusedRunTest(_FakeCodexCase):
    """`needs-input.jsonl` -- the founder text was an injected order; the answer refused it."""

    def test_a_needs_input_answer_survives_parsing_and_validation(self):
        self._queue_stdout(_fixture("needs-input.jsonl"))
        answer = self.executor.execute(
            _request(response_contract={"allowed_outcomes": ["COMPLETED", "NEEDS_INPUT"]})
        )
        self.assertEqual(answer["outcome"], "NEEDS_INPUT")
        self.assertEqual(len(answer["questions"]), 1)
        self.assertEqual(answer["questions"][0]["required"], True)


# ---------------------------------------------------------------------- the closed shape (C-1)


class TheClosedShapeTest(_FakeCodexCase):
    def test_the_argv_disables_every_feature_that_puts_a_tool_in_front_of_the_model(self):
        self._queue_stdout(_fixture("completed.jsonl"))
        self.executor.execute(_request())
        argv = self._record()["argv"]
        self.assertEqual(argv[:2], ["exec", "-"], "non-interactive, prompt on stdin")
        for flag in CODEX_EXEC_FLAGS:
            self.assertIn(flag, argv)
        disabled = [argv[i + 1] for i, a in enumerate(argv) if a == "--disable"]
        self.assertEqual(disabled, list(CODEX_DISABLED_FEATURES))
        self.assertNotIn("--output-schema", argv,
                         "strict structured outputs refuse the either/or envelope; the schema "
                         "travels in the prompt (output-schema-refused-by-strict-mode.jsonl)")

    def test_a_tool_item_in_the_stream_fails_the_job_before_its_answer_is_used(self):
        """`open-asked-to-run-a-command.jsonl` is the control: a run that could, and did, run
        `ls -a`. Its final agent_message is a perfectly good JSON object -- and the job must
        fail anyway, because the answer of a model that had a shell is not one this runtime
        forwards."""
        self._queue_stdout(_fixture("open-asked-to-run-a-command.jsonl"))
        with self.assertRaises(ExecutorUnavailable) as caught:
            self.executor.execute(_request())
        self.assertIn("closed shape was not held", str(caught.exception))
        self.assertIn("command_execution", str(caught.exception))
        self.assertIsNone(self.executor.last_envelope)

    def test_the_closed_recording_carries_no_tool_item(self):
        """`closed-asked-to-run-a-command.jsonl`: the same ask under the flags, and the model's own
        words were that no shell tool was available. Its answer is not a Keel envelope, so it is
        refused by the validator -- but by the validator, not by the closed-shape check."""
        self._queue_stdout(_fixture("closed-asked-to-run-a-command.jsonl"))
        with self.assertRaises(InvalidResponse):
            self.executor.execute(_request())
        self.assertIsNotNone(self.executor.last_schema_error)


# ---------------------------------------------------------------------- the prompt (C-2, C-8)


class ThePromptTest(_FakeCodexCase):
    def test_the_prompt_goes_on_stdin_with_system_and_response_above_the_task(self):
        self._queue_stdout(_fixture("completed.jsonl"))
        self.executor.execute(_request())
        record = self._record()
        prompt = record["stdin"]
        self.assertTrue(prompt.startswith("SYSTEM\n" + SYSTEM_PROMPT))
        self.assertIn("\nRESPONSE\n", prompt)
        self.assertIn("\nTASK\n", prompt)
        self.assertLess(prompt.index("RESPONSE"), prompt.index("TASK"))
        self.assertIn("<<<KEEL-DATA ", prompt)
        for element in record["argv"]:
            self.assertNotIn("KEEL-DATA", element, "the prompt is never an argv element")

    def test_the_job_runs_in_its_own_empty_directory_under_the_home(self):
        self._queue_stdout(_fixture("completed.jsonl"))
        self.executor.execute(_request(job_id="job-42"))
        record = self._record()
        job_dir = self.home / "jobs" / "job-42"
        self.assertTrue(job_dir.is_dir())
        self.assertEqual(Path(record["cwd"]).resolve(), job_dir.resolve())
        self.assertEqual(record["argv"][record["argv"].index("-C") + 1], str(job_dir))

    def test_the_jobs_model_travels_as_dash_m_and_a_job_without_one_sends_none(self):
        """spec 009: the model is the job's (`request.model`, the cloud's per-host routing), read
        per call -- the same executor sends `-m` on one job and nothing on the next."""
        self._queue_stdout(_fixture("completed.jsonl"))
        self.executor.execute(_request())
        self.assertNotIn("-m", self._record()["argv"])
        self.executor.execute(_request(job_id="job-2", model="gpt-6-astra"))
        argv = self._record(1)["argv"]
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-astra")
        self.assertEqual(self.executor.last_model_requested, "gpt-6-astra")
        self.assertEqual(self.executor.last_model_used, "gpt-6-astra")
        self.assertFalse(self.executor.last_retried_unpinned)


# ---------------------------------------------------------------------- the environment (C-4)


class TheEnvironmentTest(_FakeCodexCase):
    def test_the_keel_twin_of_codex_home_reaches_the_cli_under_the_real_name(self):
        """Measured 2026-09-12: Codex strips `CODEX_HOME` from the shells it runs commands in, so
        a runtime started by the skill inside a Codex session -- or a matrix cell with an
        isolated Codex home -- names it as `KEEL_CODEX_HOME`, which nothing strips."""
        self._queue_stdout(_fixture("completed.jsonl"))
        saved = {k: os.environ.get(k) for k in ("CODEX_HOME", "KEEL_CODEX_HOME")}
        os.environ.pop("CODEX_HOME", None)
        os.environ["KEEL_CODEX_HOME"] = "/tmp/an-isolated-codex-home"
        try:
            self.executor.execute(_request())
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        env = self._record()["env"]
        self.assertEqual(env.get("CODEX_HOME"), "/tmp/an-isolated-codex-home")
        self.assertNotIn("KEEL_CODEX_HOME", env)

    def test_only_codex_home_and_openai_names_travel_besides_the_common_set(self):
        self._queue_stdout(_fixture("completed.jsonl"))
        extra = {
            "CODEX_HOME": "/tmp/codex-home-for-this-test",
            "OPENAI_API_KEY": "sk-test",
            "CODEX_THREAD_ID": "parent-session",
            "CODEX_SANDBOX": "seatbelt",
            "CODEX_SANDBOX_NETWORK_DISABLED": "1",
            "ANTHROPIC_API_KEY": "not-yours",
            "COPILOT_GITHUB_TOKEN": "not-yours-either",
            "KEEL_BASE_URL": "http://localhost:18081",
        }
        saved = {k: os.environ.get(k) for k in extra}
        os.environ.update(extra)
        try:
            self.executor.execute(_request())
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        env = self._record()["env"]
        self.assertEqual(env.get("CODEX_HOME"), "/tmp/codex-home-for-this-test")
        self.assertEqual(env.get("OPENAI_API_KEY"), "sk-test")
        for absent in ("CODEX_THREAD_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED",
                       "ANTHROPIC_API_KEY", "COPILOT_GITHUB_TOKEN", "KEEL_BASE_URL"):
            self.assertNotIn(absent, env, absent)
        self.assertIn("PATH", env)


# ---------------------------------------------------------------------- failure (C-3, C-6)


class TheFailureTest(_FakeCodexCase):
    def test_an_unauthenticated_run_is_an_auth_failure_by_the_recorded_marker(self):
        self._queue({
            "stdout": _fixture("unauthenticated-no-credential.jsonl"),
            "stderr": _fixture("unauthenticated-no-credential.stderr"),
            "returncode": 1,
        })
        with self.assertRaises(ExecutorAuthFailure) as caught:
            self.executor.execute(_request())
        self.assertIn("401", str(caught.exception))

    def test_the_marker_is_read_on_stdout_events_alone_too(self):
        """A later CLI may move the words off stderr; the `error`/`turn.failed` events carry
        them as well, and either is enough."""
        self._queue({"stdout": _fixture("unauthenticated-no-credential.jsonl"), "returncode": 1})
        with self.assertRaises(ExecutorAuthFailure):
            self.executor.execute(_request())

    def test_a_strict_schema_refusal_is_unavailable_not_an_auth_failure(self):
        """`output-schema-refused-by-strict-mode.jsonl`: a `turn.failed` that is not about
        authentication stays `ExecutorUnavailable` -- the safe way to fail (design §5.4)."""
        self._queue({"stdout": _fixture("output-schema-refused-by-strict-mode.jsonl"), "returncode": 1})
        with self.assertRaises(ExecutorUnavailable) as caught:
            self.executor.execute(_request())
        self.assertIn("invalid_json_schema", str(caught.exception))

    def test_an_empty_stream_is_unavailable_with_the_stderr_or_the_exit_code(self):
        self._queue({"stdout": "", "stderr": "", "returncode": 3})
        with self.assertRaises(ExecutorUnavailable) as caught:
            self.executor.execute(_request())
        self.assertIn("exit 3", str(caught.exception))

    def test_prose_instead_of_json_gets_one_recovery_pass_quoting_the_refusal(self):
        prose = (
            '{"type":"thread.started","thread_id":"t"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"Here is a summary in words."}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        )
        self._queue_stdout(prose, _fixture("completed.jsonl"))
        answer = self.executor.execute(_request())
        self.assertEqual(answer["outcome"], "COMPLETED")
        self.assertEqual(len(self._records()), 2)
        self.assertIn("not JSON", self.executor.last_schema_error)
        self.assertIn(self.executor.last_schema_error.split(":")[0], self._record(1)["stdin"])
        self.assertTrue(self.executor.last_envelope["recovery_pass"])

    def test_a_missing_cli_is_unavailable_before_anything_runs(self):
        missing = CodexExecutor(binary="codex-that-is-not-installed", home=self.home)
        with self.assertRaises(ExecutorUnavailable):
            missing.execute(_request())

    def test_the_timeout_is_the_runtimes_own(self):
        self._queue({"stdout": "", "sleep": 2.0})
        quick = CodexExecutor(home=self.home, timeout_seconds=0.3)
        with self.assertRaises(ExecutorTimeout):
            quick.execute(_request())


if __name__ == "__main__":
    unittest.main()
