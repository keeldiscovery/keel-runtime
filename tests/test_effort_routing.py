"""spec 010-job-names-the-effort (keel-cloud `canon/designs/model-routing-design.md` §4, §5, §6).

One rule, and it is spec 009's rule applied to the second half of the same pin: the job's
`request_payload["effort"][<host_key>]` goes to the CLI as that host's effort flag; nothing else
names an effort anywhere in this runtime.

**Why it matters, in one measurement.** keel-cloud's run of record
`20260930T024851Z-instructions` certified `claude-sonnet-5-5` *at effort `medium`* -- a pair, not a
model. The Claude Code CLI's own default is `xhigh`, which that run measures at 3.7x the thinking
and 2.4x the wall clock of `medium`, for five marks `medium` already holds. Without this flag a
founder's own CLI gets the certified model and an uncertified effort.

**And what it is not**: `CLAUDE_CODE_EFFORT_LEVEL`. That variable reaches the CLI too -- `_build_env`
allow-lists the whole `CLAUDE_` prefix -- and it is process-wide, which is why keel-e2e-eval's
`judge_env()` has to strip it by name so a subject set at one level cannot silently score its own
run at that level. A per-job value belongs on a per-job argv.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from keel_runtime.executor import ClaudeCodeExecutor, ExecutorUnavailable, InferenceRequest
from keel_runtime.poller import _effort_for, _model_for

from . import test_codex_executor as codex_tests
from . import test_copilot_executor as copilot_tests
from . import test_executor as claude_tests

_FIXTURES = Path(__file__).parent / "fixtures"

#: keel-cloud v6's `claude` row, both halves.
PIN = "claude-sonnet-5-5"
EFFORT = "medium"


def _payload(model_map=None, effort_map=None) -> dict:
    payload = {
        "instruction": "Frame the problem.",
        "context": {},
        "interaction_history": [],
        "input": {"content": "the founder's framing text"},
        "response_contract": {},
    }
    if model_map is not None:
        payload["model"] = model_map
    if effort_map is not None:
        payload["effort"] = effort_map
    return payload


class TheFlagIsTheMeasuredOneTest(unittest.TestCase):
    """A flag nobody recorded is not a flag (this repository's standing rule)."""

    def test_the_recorded_help_names_the_flag_and_its_ladder(self):
        recorded = (_FIXTURES / "claude" / "effort-help.txt").read_text(encoding="utf-8")
        self.assertIn("--effort <level>", recorded)
        for level in ("low", "medium", "high", "xhigh", "max"):
            self.assertIn(level, recorded)


class EffortForTest(unittest.TestCase):
    """The poller's one step, and the four ways of meaning "no flag" -- `_model_for`'s own four."""

    def setUp(self):
        self.claude = SimpleNamespace(host_key="claude")
        self.codex = SimpleNamespace(host_key="codex")
        self.hostless = SimpleNamespace()

    def test_this_hosts_entry_is_the_answer(self):
        payload = _payload(effort_map={"claude": EFFORT, "codex": "high"})
        self.assertEqual(_effort_for(self.claude, payload), "medium")
        self.assertEqual(_effort_for(self.codex, payload), "high")

    def test_no_key_at_all_is_no_flag(self):
        self.assertIsNone(_effort_for(self.claude, _payload()))

    def test_no_entry_for_this_host_is_no_flag(self):
        # The shipped v6/v7 tables: `efforts` named `claude` alone, because neither the Codex nor
        # the Copilot executor had an effort flag to pass one to. v8 names all three (spec 011).
        self.assertIsNone(_effort_for(self.codex, _payload(effort_map={"claude": EFFORT})))

    def test_a_non_object_effort_is_no_flag(self):
        for value in ("medium", ["medium"], 7, None):
            self.assertIsNone(_effort_for(self.claude, _payload(effort_map=value)))

    def test_a_blank_or_non_string_value_is_no_flag(self):
        for value in ("", "   ", 7, None, {"nested": "no"}):
            self.assertIsNone(_effort_for(self.claude, _payload(effort_map={"claude": value})))

    def test_an_executor_with_no_host_gets_nothing(self):
        self.assertIsNone(_effort_for(self.hostless, _payload(effort_map={"claude": EFFORT})))

    def test_whitespace_is_stripped_exactly_as_the_model_is(self):
        self.assertEqual(_effort_for(self.claude, _payload(effort_map={"claude": "  medium "})), "medium")

    def test_an_unknown_word_is_passed_through_not_rejected(self):
        # FR-008. keel-cloud's table refuses a word outside the ladder at startup, with the whole
        # table in hand, and the CLI refuses one at the flag. A third opinion here could only be
        # wrong in a new way -- the day the ladder grows a sixth word, this would be what disagreed.
        self.assertEqual(_effort_for(self.claude, _payload(effort_map={"claude": "ultra"})), "ultra")

    def test_the_two_halves_are_read_independently(self):
        # A reading is the live case: it routes to the `light` tier, which names a model and no
        # effort, because `effort` ERRORS on Haiku 4.5.
        reading = _payload(model_map={"claude": "claude-haiku-4-5-20251001"})
        self.assertEqual(_model_for(self.claude, reading), "claude-haiku-4-5-20251001")
        self.assertIsNone(_effort_for(self.claude, reading))


class TheClaudeArgvTest(unittest.TestCase):
    """SC-001 and SC-003: the flag is last, and an argv without one does not move a byte."""

    def setUp(self):
        self.executor = ClaudeCodeExecutor(home="/tmp/keel-effort-argv")
        self.executor._resolved_binary = "claude"

    def test_no_effort_no_flag(self):
        self.assertNotIn("--effort", self.executor._build_argv({"type": "object"}))
        self.assertNotIn("--effort", self.executor._build_argv({"type": "object"}, PIN))

    def test_the_two_flags_are_appended_model_then_effort(self):
        argv = self.executor._build_argv({"type": "object"}, PIN, EFFORT)
        self.assertEqual(argv[-4:], ["--model", PIN, "--effort", EFFORT])

    def test_an_effort_with_no_model_is_still_passed(self):
        # Not a state the cloud's table can produce -- it refuses an `efforts` host with no `hosts`
        # row at startup -- but this method is not where that is enforced, and a silent drop here
        # would hide the table's own bug instead of letting its refusal be the one that speaks.
        argv = self.executor._build_argv({"type": "object"}, None, EFFORT)
        self.assertEqual(argv[-2:], ["--effort", EFFORT])
        self.assertNotIn("--model", argv)

    def test_an_argv_with_no_effort_is_byte_identical_to_the_one_with_only_a_model(self):
        self.assertEqual(
            self.executor._build_argv({"type": "object"}, PIN),
            self.executor._build_argv({"type": "object"}, PIN, None),
        )
        self.assertEqual(
            self.executor._build_argv({"type": "object"}, PIN),
            self.executor._build_argv({"type": "object"}, PIN, ""),
        )


class TheFlagReachesTheSubprocessTest(claude_tests._ExecutorTestBase):
    """SC-002 and SC-004, against the fake CLI: the flag in a real argv, on every pass."""

    def _good_stream(self):
        init = {"type": "system", "subtype": "init", "model": PIN}
        return claude_tests._stream(
            init, self._result_event(structured_output={"outcome": "COMPLETED", "result": {"x": "ok"}})
        )

    def test_the_jobs_effort_reaches_the_cli(self):
        self._set_raw_responses([{"stdout": self._good_stream(), "stderr": "", "returncode": 0}])
        self.executor.execute(claude_tests._request(model=PIN, effort=EFFORT))
        argv = self._records()[0]["argv"]
        self.assertEqual(argv[argv.index("--effort") + 1], EFFORT)

    def test_a_job_with_no_effort_sends_no_flag(self):
        self._set_raw_responses([{"stdout": self._good_stream(), "stderr": "", "returncode": 0}])
        self.executor.execute(claude_tests._request(model=PIN))
        self.assertNotIn("--effort", self._records()[0]["argv"])

    def test_the_effort_survives_the_unpinned_retry(self):
        """FR-005, and the reason it is its own test.

        The retry exists because the CLI refused a MODEL, by name. Dropping the effort there would
        answer one refusal with two changes, and the second one would be silent: the retry would
        quietly run at the CLI's own `xhigh` and the founder would be billed for an answer nobody
        certified. So `--model` goes and `--effort` stays.
        """
        self._set_raw_responses([
            {"stdout": (_FIXTURES / "claude" / "unknown-model.jsonl").read_text(encoding="utf-8"),
             "stderr": (_FIXTURES / "claude" / "unknown-model.stderr").read_text(encoding="utf-8"),
             "returncode": 1},
            {"stdout": self._good_stream(), "stderr": "", "returncode": 0},
        ])
        self.executor.execute(claude_tests._request(model="not-a-model", effort=EFFORT))

        first, retry = self._records()
        self.assertEqual(first["argv"][first["argv"].index("--effort") + 1], EFFORT)
        self.assertNotIn("--model", retry["argv"])
        self.assertEqual(retry["argv"][retry["argv"].index("--effort") + 1], EFFORT)
        self.assertTrue(self.executor.last_retried_unpinned)


class TheOtherTwoHostsReadTheirOwnEntryTest(unittest.TestCase):
    """Spec 011 (0.7.0) replaces spec 010's FR-006. Both CLIs now have a measured way to take the
    effort, so the poller's one rule reaches them unchanged: `request_payload["effort"][<host>]`
    and nothing else.
    """

    def test_both_build_argvs_take_an_effort_now(self):
        import inspect

        from keel_runtime.executor import CodexExecutor, CopilotExecutor

        for cls in (CodexExecutor, CopilotExecutor):
            self.assertIn("effort", inspect.signature(cls._build_argv).parameters, cls.__name__)

    def test_a_payload_carrying_an_effort_for_claude_alone_changes_nothing_for_them(self):
        # The v7 table's shape: only `claude` carried an effort, and that is still "no flag" here.
        payload = _payload(model_map={"claude": PIN, "codex": "gpt-5.6-terra"},
                           effort_map={"claude": EFFORT})
        self.assertIsNone(_effort_for(SimpleNamespace(host_key="codex"), payload))
        self.assertIsNone(_effort_for(SimpleNamespace(host_key="copilot"), payload))

    def test_the_v8_table_names_every_host_and_each_reads_its_own(self):
        payload = _payload(model_map={"claude": PIN, "codex": "gpt-5.6-terra", "copilot": "gpt-5.6-terra"},
                           effort_map={"claude": "medium", "codex": "medium", "copilot": "medium"})
        for host in ("claude", "codex", "copilot"):
            self.assertEqual(_effort_for(SimpleNamespace(host_key=host), payload), "medium", host)


# --------------------------------------------------------------------- spec 011: Codex (0.7.0)


class TheCodexFlagIsTheMeasuredOneTest(unittest.TestCase):
    """A flag nobody recorded is not a flag. On this CLI there is no flag at all: `-c` is a generic
    config override, the key is `model_reasoning_effort`, and the ladder is the catalogue's."""

    def test_the_recorded_help_is_the_config_override_and_names_no_effort_flag(self):
        recorded = (_FIXTURES / "codex" / "exec-config-help.txt").read_text(encoding="utf-8")
        self.assertIn("-c, --config <key=value>", recorded)
        self.assertIn("parsed\n          as TOML", recorded)
        self.assertNotIn("--effort", recorded)

    def test_the_manifest_row_names_the_ladder_the_constant_carries(self):
        import json

        from keel_runtime.executor import CODEX_EFFORT_LADDER

        manifest = json.loads((_FIXTURES / "codex" / "MANIFEST.json").read_text(encoding="utf-8"))
        note = manifest["recordings"]["exec-config-help.txt"]["note"]
        self.assertEqual(CODEX_EFFORT_LADDER, ("low", "medium", "high", "xhigh"))
        for word in CODEX_EFFORT_LADDER:
            self.assertIn(f"`{word}`", note)
        self.assertIn("model_reasoning_effort", note)


class TheCodexArgvTest(unittest.TestCase):
    """SC-001/SC-003 for this host: the override is last, after `-m`, and an argv without an effort
    does not move a byte."""

    def setUp(self):
        from keel_runtime.executor import CodexExecutor

        self.executor = CodexExecutor(home="/tmp/keel-effort-argv-codex")
        self.executor._resolved_binary = "codex"
        self.job_dir = Path("/tmp/keel-effort-argv-codex/jobs/j")

    def test_no_effort_no_override(self):
        for argv in (self.executor._build_argv(self.job_dir),
                     self.executor._build_argv(self.job_dir, "gpt-5.6-terra")):
            self.assertNotIn("-c", argv)
            self.assertFalse(any("model_reasoning_effort" in a for a in argv))
            self.assertNotIn("--effort", argv)

    def test_the_override_is_appended_after_the_model(self):
        argv = self.executor._build_argv(self.job_dir, "gpt-5.6-terra", "medium")
        self.assertEqual(argv[-4:], ["-m", "gpt-5.6-terra", "-c", "model_reasoning_effort=medium"])
        self.assertNotIn("--effort", argv)

    def test_an_effort_with_no_model_is_still_passed(self):
        argv = self.executor._build_argv(self.job_dir, None, "high")
        self.assertEqual(argv[-2:], ["-c", "model_reasoning_effort=high"])
        self.assertNotIn("-m", argv)

    def test_an_argv_with_no_effort_is_byte_identical_to_the_pre_0_7_0_one(self):
        with_model = self.executor._build_argv(self.job_dir, "gpt-5.6-terra")
        self.assertEqual(with_model, self.executor._build_argv(self.job_dir, "gpt-5.6-terra", None))
        self.assertEqual(with_model, self.executor._build_argv(self.job_dir, "gpt-5.6-terra", ""))
        self.assertEqual(with_model[:-2], self.executor._build_argv(self.job_dir))

    def test_every_word_on_the_ladder_is_accepted_and_only_those(self):
        from keel_runtime.executor import CODEX_EFFORT_LADDER

        for word in CODEX_EFFORT_LADDER:
            argv = self.executor._build_argv(self.job_dir, "gpt-5.6-terra", word)
            self.assertEqual(argv[-1], f"model_reasoning_effort={word}")
        # `max` and `ultra` ARE in the catalogue for terra -- and not for every model, so they are
        # not on the common ladder and are refused by name rather than passed at a guess. `none`
        # is Copilot's word, `ultra` nobody's on this runtime, `MEDIUM` is not `medium`.
        for word in ("max", "ultra", "none", "minimal", "MEDIUM", "medium "):
            with self.assertRaises(ExecutorUnavailable) as caught:
                self.executor._build_argv(self.job_dir, "gpt-5.6-terra", word)
            self.assertIn(repr(word), str(caught.exception))
            self.assertIn("low, medium, high, xhigh", str(caught.exception))
            self.assertIn("codex", str(caught.exception))


class TheCodexFlagReachesTheSubprocessTest(codex_tests._FakeCodexCase):
    """SC-002/SC-004 for this host, against the fake CLI: the override in a real argv, on every
    pass, and a word off the ladder spawns nothing."""

    def test_the_jobs_effort_reaches_the_cli_after_the_model(self):
        self._queue_stdout(codex_tests._fixture("completed.jsonl"))
        self.executor.execute(codex_tests._request(model="gpt-5.6-terra", effort="medium"))
        argv = self._record()["argv"]
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5.6-terra")
        self.assertEqual(argv[argv.index("-c") + 1], "model_reasoning_effort=medium")
        self.assertGreater(argv.index("-c"), argv.index("-m"))

    def test_a_job_with_no_effort_sends_no_override(self):
        self._queue_stdout(codex_tests._fixture("completed.jsonl"))
        self.executor.execute(codex_tests._request(model="gpt-5.6-terra"))
        self.assertNotIn("-c", self._record()["argv"])

    def test_the_effort_survives_the_unpinned_retry(self):
        # spec 010 FR-005, kept for this host: the CLI refused a MODEL by name, so `-m` goes and the
        # override stays -- otherwise the retry would silently run at the catalogue default.
        self._queue(
            {"stdout": codex_tests._fixture("unsupported-model-on-plan.jsonl"),
             "stderr": codex_tests._fixture("unsupported-model-on-plan.stderr"), "returncode": 1},
            {"stdout": codex_tests._fixture("completed.jsonl"), "returncode": 0},
        )
        self.executor.execute(codex_tests._request(model="gpt-5.5-mini", effort="medium"))
        first, retry = self._records()
        self.assertIn("model_reasoning_effort=medium", first["argv"])
        self.assertNotIn("-m", retry["argv"])
        self.assertEqual(retry["argv"][retry["argv"].index("-c") + 1], "model_reasoning_effort=medium")
        self.assertTrue(self.executor.last_retried_unpinned)

    def test_the_effort_survives_the_recovery_pass(self):
        # Prose where JSON was wanted earns one recovery pass (spec 008 FR-011's shape on this
        # host); the recovery runs at the same model AND the same effort.
        prose = (
            '{"type":"thread.started","thread_id":"t"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"Here is a summary in words."}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        )
        self._queue_stdout(prose, codex_tests._fixture("completed.jsonl"))
        self.executor.execute(codex_tests._request(model="gpt-5.6-terra", effort="medium"))
        first, recovery = self._records()
        for record in (first, recovery):
            self.assertEqual(record["argv"][record["argv"].index("-m") + 1], "gpt-5.6-terra")
            self.assertEqual(record["argv"][record["argv"].index("-c") + 1], "model_reasoning_effort=medium")
        self.assertTrue(self.executor.last_envelope["recovery_pass"])

    def test_a_word_off_the_ladder_fails_this_job_by_name_and_spawns_nothing(self):
        self._queue_stdout(codex_tests._fixture("completed.jsonl"))
        with self.assertRaises(ExecutorUnavailable) as caught:
            self.executor.execute(codex_tests._request(model="gpt-5.6-terra", effort="ultra"))
        self.assertIn("'ultra'", str(caught.exception))
        self.assertFalse((self.bin_dir / "records.json").exists(), "the CLI must not have been run")


# ------------------------------------------------------------------- spec 011: Copilot (0.7.0)


class TheCopilotFlagIsTheMeasuredOneTest(unittest.TestCase):
    def test_the_recorded_help_names_the_flag_and_its_seven_choices(self):
        from keel_runtime.executor import COPILOT_EFFORT_LADDER

        recorded = (_FIXTURES / "copilot" / "effort-help.txt").read_text(encoding="utf-8")
        self.assertIn("--effort, --reasoning-effort <level>", recorded)
        self.assertEqual(COPILOT_EFFORT_LADDER, ("none", "minimal", "low", "medium", "high", "xhigh", "max"))
        for word in COPILOT_EFFORT_LADDER:
            self.assertIn(f'"{word}"', recorded)


class TheCopilotArgvTest(unittest.TestCase):
    def setUp(self):
        from keel_runtime.executor import CopilotExecutor

        self.executor = CopilotExecutor(home="/tmp/keel-effort-argv-copilot")
        self.executor._resolved_binary = "copilot"
        self.job_dir = Path("/tmp/keel-effort-argv-copilot/jobs/j")

    def test_no_effort_no_flag(self):
        self.assertNotIn("--effort", self.executor._build_argv(self.job_dir))
        self.assertNotIn("--effort", self.executor._build_argv(self.job_dir, "gpt-5.6-terra"))

    def test_the_two_flags_are_appended_model_then_effort(self):
        argv = self.executor._build_argv(self.job_dir, "gpt-5.6-terra", "medium")
        self.assertEqual(argv[-4:], ["--model", "gpt-5.6-terra", "--effort", "medium"])

    def test_an_effort_with_no_model_is_still_passed(self):
        argv = self.executor._build_argv(self.job_dir, None, "low")
        self.assertEqual(argv[-2:], ["--effort", "low"])
        self.assertNotIn("--model", argv)

    def test_an_argv_with_no_effort_is_byte_identical_to_the_pre_0_7_0_one(self):
        with_model = self.executor._build_argv(self.job_dir, "gpt-5.6-terra")
        self.assertEqual(with_model, self.executor._build_argv(self.job_dir, "gpt-5.6-terra", None))
        self.assertEqual(with_model, self.executor._build_argv(self.job_dir, "gpt-5.6-terra", ""))

    def test_every_word_on_the_ladder_is_accepted_and_only_those(self):
        from keel_runtime.executor import COPILOT_EFFORT_LADDER

        for word in COPILOT_EFFORT_LADDER:
            self.assertEqual(self.executor._build_argv(self.job_dir, "gpt-5.6-terra", word)[-1], word)
        for word in ("ultra", "MEDIUM", "medium ", "mediums"):
            with self.assertRaises(ExecutorUnavailable) as caught:
                self.executor._build_argv(self.job_dir, "gpt-5.6-terra", word)
            self.assertIn(repr(word), str(caught.exception))
            self.assertIn("none, minimal, low, medium, high, xhigh, max", str(caught.exception))
            self.assertIn("copilot", str(caught.exception))


class TheCopilotFlagReachesTheSubprocessTest(copilot_tests._FakeCopilotCase):
    def test_the_jobs_effort_reaches_the_cli_after_the_model(self):
        self._queue_stdout(copilot_tests._fixture("completed.jsonl"))
        self.executor.execute(copilot_tests._request(model="gpt-5.6-terra", effort="medium"))
        argv = self._record()["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-5.6-terra")
        self.assertEqual(argv[argv.index("--effort") + 1], "medium")
        self.assertGreater(argv.index("--effort"), argv.index("--model"))

    def test_a_job_with_no_effort_sends_no_flag(self):
        self._queue_stdout(copilot_tests._fixture("completed.jsonl"))
        self.executor.execute(copilot_tests._request(model="gpt-5.6-terra"))
        self.assertNotIn("--effort", self._record()["argv"])

    def test_the_effort_survives_the_unpinned_retry(self):
        self._queue(
            {"stdout": "", "stderr": copilot_tests._fixture("unknown-model.stderr"), "returncode": 1},
            {"stdout": copilot_tests._fixture("completed.jsonl"), "returncode": 0},
        )
        self.executor.execute(copilot_tests._request(model="not-a-model", effort="medium"))
        first, retry = self._records()
        self.assertEqual(first["argv"][first["argv"].index("--effort") + 1], "medium")
        self.assertNotIn("--model", retry["argv"])
        self.assertEqual(retry["argv"][retry["argv"].index("--effort") + 1], "medium")
        self.assertTrue(self.executor.last_retried_unpinned)

    def test_a_word_off_the_ladder_fails_this_job_by_name_and_spawns_nothing(self):
        self._queue_stdout(copilot_tests._fixture("completed.jsonl"))
        with self.assertRaises(ExecutorUnavailable) as caught:
            self.executor.execute(copilot_tests._request(model="gpt-5.6-terra", effort="ultra"))
        self.assertIn("'ultra'", str(caught.exception))
        self.assertFalse((self.bin_dir / "records.json").exists(), "the CLI must not have been run")


class ThereIsNoEffortKnobTest(unittest.TestCase):
    """FR-007, the twin of spec 009's rule for the model.

    The effort comes with the job and from nowhere else. A knob here would be a second source of
    truth -- what spec 009 spent 0.5.0 removing -- and it would be process-wide, which is the thing
    keel-e2e-eval's judge already has to defend itself against.
    """

    def test_the_config_carries_no_effort_flag_variable_or_key(self):
        from keel_runtime import cli, config

        for module in (config, cli):
            names = [name for name in dir(module) if "EFFORT" in name.upper()]
            self.assertEqual(names, [], module.__name__)

    def test_the_executor_takes_no_effort_in_its_constructor(self):
        with self.assertRaises(TypeError):
            ClaudeCodeExecutor(home="/tmp/x", effort=EFFORT)

    def test_the_request_field_defaults_to_none(self):
        request = InferenceRequest(job_id="j", interaction_id="i", turn_number=1, request_payload={})
        self.assertIsNone(request.effort)
        self.assertIsNone(request.model)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
