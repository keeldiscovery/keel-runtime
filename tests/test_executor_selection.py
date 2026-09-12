"""Tests for **which executor runs** (spec `005-copilot-executor`; design §5.3, C-9, C-10, C-12).

Five steps, in order, and the whole point of the first one is that the founder can always end
the argument:

```
1  explicit:  --executor  >  KEEL_EXECUTOR  >  $KEEL_HOME/config.json["executor"]
              -> that one, always, even if its CLI is missing (it reports per job)
2  host:      --host, then the environment this process was launched into
              -> exactly one answer, take it; two different answers, take NEITHER
3  PATH:      exactly one of `copilot` / `claude` on PATH  -> that one
4  both on PATH and nothing above decided  -> claude, and say so
5  neither on PATH -> claude, and print KEEL_EXECUTOR_UNAVAILABLE
```

`PATH` is faked here by replacing `shutil.which` inside `config`, so the table is the same on the
founder's Mac (both CLIs installed) as on a CI runner (neither).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from keel_runtime import cli as cli_module
from keel_runtime import config as config_module

_RUNTIME_DIR = Path(__file__).resolve().parents[1]


def _args(**kwargs):
    kwargs.setdefault("executor", None)
    kwargs.setdefault("host", None)
    return SimpleNamespace(**kwargs)


class _WhichCase(unittest.TestCase):
    """Fakes what is on `PATH` for the duration of a test."""

    def _on_path(self, *names):
        present = set(names)
        real_which = shutil.which

        def fake_which(binary, *rest, **kwargs):
            if binary in ("claude", "copilot", "codex"):
                return "/fake/bin/" + binary if binary in present else None
            return real_which(binary, *rest, **kwargs)

        patched = getattr(config_module, "shutil")
        original = patched.which
        patched.which = fake_which
        self.addCleanup(setattr, patched, "which", original)


class TheSelectionOrderTest(_WhichCase):
    """The table, row by row, as a table."""

    def test_the_whole_table(self):
        cases = [
            # (label, args, env, on PATH, expected name, expected source)
            (
                "a flag wins over everything, including its own missing CLI",
                _args(executor="copilot"),
                {"KEEL_EXECUTOR": "claude", "CLAUDECODE": "1"},
                (),
                "copilot",
                "flag",
            ),
            (
                "the flag's permanent alias resolves to the canonical name",
                _args(executor="claude-code"),
                {},
                ("copilot",),
                "claude",
                "flag",
            ),
            (
                "KEEL_EXECUTOR beats config.json and every host marker",
                _args(),
                {"KEEL_EXECUTOR": "copilot", "CLAUDECODE": "1"},
                ("claude",),
                "copilot",
                "env",
            ),
            (
                "a host marker beats PATH",
                _args(),
                {"CLAUDECODE": "1"},
                ("copilot",),
                "claude",
                "host",
            ),
            (
                "COPILOT_AGENT_SESSION_ID alone names copilot",
                _args(),
                {"COPILOT_AGENT_SESSION_ID": "sess-1"},
                ("claude", "copilot"),
                "copilot",
                "host",
            ),
            (
                "COPILOT_CLI=1 alone names copilot",
                _args(),
                {"COPILOT_CLI": "1"},
                (),
                "copilot",
                "host",
            ),
            (
                "AI_AGENT is the nearest cross-vendor convention, and it counts",
                _args(),
                {"AI_AGENT": "github_copilot/1.0.83"},
                (),
                "copilot",
                "host",
            ),
            (
                "CODEX_THREAD_ID alone names codex (spec 008)",
                _args(),
                {"CODEX_THREAD_ID": "01a09670-929a-7fb1-867d-8fb479ada847"},
                ("claude", "copilot", "codex"),
                "codex",
                "host",
            ),
            (
                "CODEX_SESSION_ID alone names codex too",
                _args(),
                {"CODEX_SESSION_ID": "01a09670-929a-7fb1-867d-8fb479ada847"},
                (),
                "codex",
                "host",
            ),
            (
                "a Codex session inside Claude Code is two answers, so no answer",
                _args(),
                {"CODEX_THREAD_ID": "x", "CLAUDECODE": "1"},
                ("codex",),
                "codex",
                "path",
            ),
            (
                "codex alone on PATH is the answer when nothing above decided",
                _args(),
                {},
                ("codex",),
                "codex",
                "path",
            ),
            (
                "three CLIs on PATH and nothing above decided is claude, said out loud",
                _args(),
                {},
                ("claude", "copilot", "codex"),
                "claude",
                "ambiguous-path",
            ),
            (
                "AI_AGENT naming Claude Code counts the same way",
                _args(),
                {"AI_AGENT": "claude-code/2.1.259"},
                (),
                "claude",
                "host",
            ),
            (
                "**two host answers mean no answer** -- fall through to PATH",
                _args(),
                {"CLAUDECODE": "1", "COPILOT_AGENT_SESSION_ID": "sess-1"},
                ("copilot",),
                "copilot",
                "path",
            ),
            (
                "exactly one CLI on PATH is the answer when nothing above decided",
                _args(),
                {},
                ("claude",),
                "claude",
                "path",
            ),
            (
                "both on PATH and nothing above decided -> claude, and say so",
                _args(),
                {},
                ("claude", "copilot"),
                "claude",
                "ambiguous-path",
            ),
            (
                "neither on PATH -> claude, and the caller says it is unavailable",
                _args(),
                {},
                (),
                "claude",
                "default",
            ),
            (
                "--host is a host signal: below every explicit term, above the markers",
                _args(host="copilot"),
                {"CLAUDECODE": "1"},
                ("claude",),
                "copilot",
                "host",
            ),
            (
                "--host auto means 'read the markers yourself'",
                _args(host="auto"),
                {"CLAUDECODE": "1"},
                (),
                "claude",
                "host",
            ),
            (
                "--host never outranks --executor",
                _args(executor="claude", host="copilot"),
                {},
                (),
                "claude",
                "flag",
            ),
        ]
        for label, args, env, present, expected_name, expected_source in cases:
            with self.subTest(row=label):
                self._on_path(*present)
                name, source = config_module.resolve_executor(args, {}, environ=env)
                self.assertEqual((name, source), (expected_name, expected_source))

    def test_config_json_is_the_last_explicit_term(self):
        self._on_path("claude")
        name, source = config_module.resolve_executor(
            _args(), {"executor": "copilot"}, environ={"CLAUDECODE": "1"}
        )
        self.assertEqual((name, source), ("copilot", "config"))

    def test_an_explicit_name_wins_even_with_no_cli_anywhere(self):
        """Step 1 wins **even if its CLI is missing**: a founder who names an executor is
        answering the question, and a runtime that second-guesses them has taken the answer
        away. The missing CLI is reported per job as `EXECUTOR_UNAVAILABLE`.
        """
        self._on_path()
        self.assertEqual(
            config_module.resolve_executor(_args(executor="copilot"), {}, environ={}),
            ("copilot", "flag"),
        )

    def test_every_source_this_resolver_can_return_is_in_the_declared_vocabulary(self):
        for source in ("flag", "env", "config", "host", "path", "ambiguous-path", "default"):
            self.assertIn(source, config_module.EXECUTOR_SOURCES)


class HostMarkersTest(unittest.TestCase):
    """`host_from_environment` on its own, including the case that taught the design the rule."""

    def test_two_hosts_at_once_is_no_answer(self):
        """Not hypothetical: the environment dump that taught this design those variable names
        was `copilot` running *inside* Claude Code, carrying both hosts' markers at once.
        `COPILOT_AGENT_SESSION_ID` leaks arbitrarily deep down a process tree -- it means
        "somewhere in my ancestry", never "my parent".
        """
        self.assertIsNone(
            config_module.host_from_environment(
                {"CLAUDECODE": "1", "COPILOT_AGENT_SESSION_ID": "sess-1"}
            )
        )

    def test_two_markers_agreeing_is_still_one_answer(self):
        self.assertEqual(
            config_module.host_from_environment(
                {"COPILOT_CLI": "1", "COPILOT_AGENT_SESSION_ID": "sess-1"}
            ),
            "copilot",
        )

    def test_an_empty_or_absent_marker_says_nothing(self):
        for environ in ({}, {"COPILOT_AGENT_SESSION_ID": ""}, {"CLAUDECODE": "0"},
                        {"CLAUDECODE": ""}, {"AI_AGENT": "something-else"}):
            with self.subTest(environ=environ):
                self.assertIsNone(config_module.host_from_environment(environ))


class TheStartupLineTest(_WhichCase):
    """C-9: **the runtime says which, always** -- one line at startup, into the log the skill is
    already reading, in the same machine-readable family as `KEEL_USER_CODE=`.
    """

    def _config(self, **kwargs):
        kwargs.setdefault("executor", "claude")
        kwargs.setdefault("executor_source", "default")
        kwargs.setdefault("copilot_model", None)
        return SimpleNamespace(**kwargs)

    def _no_version_probe(self):
        original = cli_module._binary_version
        cli_module._binary_version = lambda path: None
        self.addCleanup(setattr, cli_module, "_binary_version", original)

    def test_it_names_the_executor_and_why(self):
        self._on_path("copilot")
        self._no_version_probe()
        lines = cli_module.executor_startup_lines(
            self._config(executor="copilot", executor_source="host")
        )
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("KEEL_EXECUTOR=copilot source=host "))
        self.assertIn("binary=/fake/bin/copilot", lines[0])

    def test_an_ambiguous_path_says_so_and_says_what_to_do(self):
        self._on_path("claude", "copilot")
        self._no_version_probe()
        line = cli_module.executor_startup_lines(
            self._config(executor="claude", executor_source="ambiguous-path")
        )[0]
        self.assertIn("source=ambiguous-path", line)
        self.assertIn("more than one host CLI on PATH", line)
        self.assertIn("--executor", line)

    def test_a_missing_cli_gets_its_own_line_and_still_connects(self):
        """The runtime still connects: the founder's device is authorized either way, and each
        job reports `EXECUTOR_UNAVAILABLE` on its own -- a far better failure than refusing to
        connect at all.
        """
        self._on_path()
        lines = cli_module.executor_startup_lines(
            self._config(executor="copilot", executor_source="flag")
        )
        self.assertEqual(len(lines), 2)
        self.assertIn("KEEL_EXECUTOR=copilot source=flag", lines[0])
        self.assertTrue(lines[1].startswith("KEEL_EXECUTOR_UNAVAILABLE=copilot"))
        self.assertIn("EXECUTOR_UNAVAILABLE", lines[1])

    def test_an_unpinned_copilot_run_says_model_auto_out_loud(self):
        """C-5: a Copilot subject that does not pin `--model` measures the router, not a model.
        An unpinned run must be visible in the log, never inferred from a missing word.
        """
        self._on_path("copilot")
        self._no_version_probe()
        unpinned = cli_module.executor_startup_lines(
            self._config(executor="copilot", executor_source="path")
        )[0]
        pinned = cli_module.executor_startup_lines(
            self._config(executor="copilot", executor_source="path", copilot_model="gpt-5.4")
        )[0]
        self.assertIn("model=auto", unpinned)
        self.assertIn("model=gpt-5.4", pinned)

    def test_an_unpinned_codex_run_says_model_default_out_loud(self):
        """spec 008: unpinned, `codex exec` answers with the account's default model (measured
        `gpt-6-astra`), and the line says `model=default` rather than leaving it to be inferred."""
        self._on_path("codex")
        self._no_version_probe()
        line = cli_module.executor_startup_lines(
            self._config(executor="codex", executor_source="host", codex_model=None)
        )[0]
        self.assertIn("KEEL_EXECUTOR=codex", line)
        self.assertIn("model=default", line)
        pinned = cli_module.executor_startup_lines(
            self._config(executor="codex", executor_source="flag", codex_model="gpt-6-astra")
        )[0]
        self.assertIn("model=gpt-6-astra", pinned)

    def test_the_claude_line_carries_no_model_key(self):
        self._on_path("claude")
        self._no_version_probe()
        line = cli_module.executor_startup_lines(
            self._config(executor="claude", executor_source="path")
        )[0]
        self.assertNotIn("model=", line)

    def test_the_version_is_printed_when_it_is_cheap_to_have(self):
        self._on_path("copilot")
        original = cli_module._binary_version
        cli_module._binary_version = lambda path: "GitHub Copilot CLI 1.0.83."
        self.addCleanup(setattr, cli_module, "_binary_version", original)
        line = cli_module.executor_startup_lines(
            self._config(executor="copilot", executor_source="host")
        )[0]
        self.assertIn("version=GitHub Copilot CLI 1.0.83.", line)

    def test_an_in_process_executor_is_never_reported_unavailable(self):
        self._on_path()
        lines = cli_module.executor_startup_lines(
            self._config(executor="scripted", executor_source="flag")
        )
        self.assertEqual(lines, ["KEEL_EXECUTOR=scripted source=flag"])


class StatusReportsTheResolvedChoiceTest(unittest.TestCase):
    """C-10: `keel status` carries `executor` and `executor_on_path` in **both** shapes, and both
    reflect what the selection order actually resolved. A `claude_on_path` boolean is never
    built, because it reads `false` on a healthy Copilot-hosted runtime, which is a lie about
    health.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fake_home = Path(self._tmp.name)

    def _payload(self, **env_overrides):
        env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
        for marker in config_module.ENV_HOST_MARKERS:
            env.pop(marker, None)
        env["HOME"] = str(self.fake_home)
        env["USERPROFILE"] = str(self.fake_home)
        env.update(env_overrides)
        result = subprocess.run(
            [sys.executable, "-m", "keel_runtime", "status"],
            cwd=str(_RUNTIME_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_an_explicit_copilot_is_reported_as_copilot(self):
        payload = self._payload(KEEL_EXECUTOR="copilot")
        self.assertEqual(payload["executor"], "copilot")
        self.assertEqual(payload["executor_on_path"], shutil.which("copilot") is not None)

    def test_the_permanent_alias_is_reported_under_its_canonical_name(self):
        self.assertEqual(self._payload(KEEL_EXECUTOR="claude-code")["executor"], "claude")

    def test_a_copilot_host_marker_alone_makes_status_say_copilot(self):
        payload = self._payload(COPILOT_CLI="1")
        self.assertEqual(payload["executor"], "copilot")

    def test_claude_on_path_is_never_a_key(self):
        payload = self._payload(KEEL_EXECUTOR="copilot")
        self.assertNotIn("claude_on_path", payload)
        self.assertNotIn("copilot_on_path", payload)

    def test_status_still_exits_zero_and_prints_one_line_with_a_nonsense_executor(self):
        """R-4: `status` never exits non-zero, in any case."""
        payload = self._payload(KEEL_EXECUTOR="no-such-executor")
        self.assertEqual(payload["executor"], "no-such-executor")
        self.assertFalse(payload["executor_on_path"])


class ConnectAcceptsHostTest(unittest.TestCase):
    """design §5.3: **the skill passes the host through.** `keel_connect_check.py` gains
    `--host {claude,copilot,auto}` and passes it to the `connect` it launches -- so `connect`
    must accept it, and must not have grown a new outcome key to carry it (decision 15).
    """

    def test_connect_accepts_host_and_copilot_model(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["connect", "--host", "copilot", "--copilot-model", "gpt-5.4"])
        self.assertEqual(args.host, "copilot")
        self.assertEqual(args.copilot_model, "gpt-5.4")

    def test_host_defaults_to_auto(self):
        self.assertEqual(cli_module.build_parser().parse_args(["connect"]).host, "auto")

    def test_host_rejects_anything_that_is_not_a_host(self):
        parser = cli_module.build_parser()
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                parser.parse_args(["connect", "--host", "gemini"])

    def test_executor_accepts_both_canonical_names_and_the_permanent_alias(self):
        parser = cli_module.build_parser()
        for name in ("claude", "claude-code", "copilot", "scripted", "stub"):
            with self.subTest(name=name):
                self.assertEqual(
                    parser.parse_args(["connect", "--executor", name]).executor, name
                )

    def test_status_and_disconnect_have_no_host_flag(self):
        """`--host` is about *running jobs*. Neither `status` nor `disconnect` runs one."""
        parser = cli_module.build_parser()
        for command in ("status", "disconnect"):
            with self.subTest(command=command):
                with self.assertRaises(SystemExit):
                    with redirect_stdout(io.StringIO()):
                        parser.parse_args([command, "--host", "copilot"])


class TheCopilotModelResolutionTest(unittest.TestCase):
    def test_flag_beats_env_beats_file_beats_unpinned(self):
        self.assertEqual(
            config_module.resolve_copilot_model(
                SimpleNamespace(copilot_model="from-flag"),
                {"copilot_model": "from-file"},
                environ={"KEEL_COPILOT_MODEL": "from-env"},
            ),
            "from-flag",
        )
        self.assertEqual(
            config_module.resolve_copilot_model(
                SimpleNamespace(copilot_model=None),
                {"copilot_model": "from-file"},
                environ={"KEEL_COPILOT_MODEL": "from-env"},
            ),
            "from-env",
        )
        self.assertEqual(
            config_module.resolve_copilot_model(
                SimpleNamespace(copilot_model=None), {"copilot_model": "from-file"}, environ={}
            ),
            "from-file",
        )
        self.assertIsNone(
            config_module.resolve_copilot_model(
                SimpleNamespace(copilot_model=None), {}, environ={}
            )
        )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(unittest.main())
