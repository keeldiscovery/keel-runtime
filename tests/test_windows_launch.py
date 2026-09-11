"""Windows launches the host CLIs without `cmd.exe` (spec `006-executor-shape-and-windows`
FR-003..FR-006).

**What was measured.** On staging (keel-e2e-eval runs 34566001772 and 34607630153, the Windows
Claude cells) the runtime resolved `claude` to `C:\\npm\\prefix\\claude.CMD`, launched it, and the
job died with **exit 255 and no output at all**, or with
`The filename, directory name, or volume label syntax is incorrect.` -- `cmd.exe`, which the OS
loader puts in the chain for any `.cmd`, re-parsing an argument list full of the characters a batch
file treats as syntax: the `--system-prompt` sentence and the `--json-schema` JSON. Spec 005's
amendment moved the *prompt* to stdin; the flags still travelled that road, and this is the rest of
the fix.

**What these tests run against.** `tests/fixtures/windows/*.cmd` are npm's own generator's output
(`MANIFEST.json` says how they were produced), so the parser is tested against the artifact rather
than against somebody's memory of it. `os.name` is monkey-patched to `"nt"` where the Windows
branch is the point -- `shutil.which` and `subprocess` both branch on `sys.platform`, not `os.name`
(CPython), so the patch reaches this module's own rule and nothing else -- and the end-to-end cases
run a **real `node`** against a fake `cli.js`, which is exactly the shape the fix produces. Nothing
here needs a Windows machine, and nothing here changes on macOS or Linux.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel_runtime import executor as executor_module
from keel_runtime.executor import (
    SYSTEM_PROMPT,
    ClaudeCodeExecutor,
    CopilotExecutor,
    InferenceRequest,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "windows"
_COPILOT_FIXTURES = Path(__file__).parent / "fixtures" / "copilot"

_SHIM_TARGETS = {
    "claude.cmd": "node_modules/@anthropic-ai/claude-code/cli.js",
    "claude-native.cmd": "node_modules/@anthropic-ai/claude-code/bin/claude.exe",
    "copilot.cmd": "node_modules/@github/copilot/index.js",
    "hand-written-python.cmd": "fake-cli.py",
}

# A fake host CLI as **real JavaScript**, so a real `node` runs it -- which is the whole point:
# the argv under test is the one `[node, <entry>, *flags]` produces. Records every invocation
# (argv, stdin, cwd, and node's own flags) beside itself and replays one queued response, the
# same contract the Python fakes in `test_executor.py` and `test_copilot_executor.py` use.
_FAKE_CLI_JS = r"""
const fs = require("fs");
const path = require("path");

const here = path.dirname(__filename);
const recordsPath = path.join(here, "records.json");

let records = [];
if (fs.existsSync(recordsPath)) {
  records = JSON.parse(fs.readFileSync(recordsPath, "utf8"));
}

let stdin = "";
try {
  stdin = fs.readFileSync(0, "utf8");
} catch (err) {
  stdin = "";
}

records.push({
  argv: process.argv.slice(2),
  stdin: stdin,
  cwd: process.cwd(),
  execArgv: process.execArgv,
});
fs.writeFileSync(recordsPath, JSON.stringify(records));

const responses = JSON.parse(fs.readFileSync(path.join(here, "responses.json"), "utf8"));
const response = responses[Math.min(records.length - 1, responses.length - 1)];
process.stdout.write(response.stdout || "");
process.stderr.write(response.stderr || "");
process.exit(response.returncode || 0);
"""


def _install_shim(root: Path, name: str, js_source: str | None = None) -> Path:
    """Lays out an npm install's shape under `root`: the recorded `.cmd` shim, and the file it
    names. Returns the shim's path.
    """
    shim = root / name
    shim.write_bytes((_FIXTURES / name).read_bytes())
    shim.chmod(0o755)

    target = root / _SHIM_TARGETS[name]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(js_source if js_source is not None else "// entry point\n", encoding="utf-8")
    return shim


def _request(job_id="job-1", response_contract=None, content="the founder's framing text"):
    return InferenceRequest(
        job_id=job_id,
        interaction_id="interaction-1",
        turn_number=1,
        request_payload={
            "instruction": "Frame the problem.",
            "context": {},
            "interaction_history": [],
            "input": {"content": content},
            "response_contract": response_contract
            or {
                "allowed_outcomes": ["NEEDS_INPUT", "COMPLETED"],
                "completed_result_schema": {
                    "type": "object",
                    "required": ["statement"],
                    "properties": {"statement": {"type": "string", "maxLength": 400}},
                },
            },
        },
    )


class ShimParsingTest(unittest.TestCase):
    """FR-003: the JavaScript entry point is **read out of the shim**, never guessed from a
    package name -- guessing would be a claim about somebody else's install layout.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_the_claude_shim_names_its_cli_js(self):
        shim = _install_shim(self.root, "claude.cmd")
        kind, entry, node_args, after = executor_module._cmd_shim_launch(str(shim))
        self.assertEqual(kind, "node")
        self.assertEqual(after, [])
        self.assertEqual(
            Path(entry).resolve(),
            (self.root / "node_modules/@anthropic-ai/claude-code/cli.js").resolve(),
        )
        self.assertEqual(node_args, [])

    def test_the_copilot_shim_carries_its_targets_shebang_flags(self):
        """npm copies the target's own `#!/usr/bin/env node --enable-source-maps` into the
        shim, so the launcher carries them too -- starting the program without them would be
        starting it differently from the way its own installer does.
        """
        shim = _install_shim(self.root, "copilot.cmd")
        _, entry, node_args, _after = executor_module._cmd_shim_launch(str(shim))
        self.assertTrue(entry.endswith(os.path.join("@github", "copilot", "index.js")))
        self.assertEqual(node_args, ["--enable-source-maps"])

    def test_the_pathext_line_is_not_mistaken_for_a_path(self):
        """The generated shim contains `SET PATHEXT=%PATHEXT:;.JS;=;%`. A looser parser reads
        that as a file name; this one only looks at quoted tokens, and only returns a path that
        exists.
        """
        shim = _install_shim(self.root, "claude.cmd")
        text = shim.read_text(encoding="utf-8")
        self.assertIn("%PATHEXT:;.JS;=;%", text)
        without_launch_line = "\r\n".join(
            line for line in text.splitlines() if "%_prog%" not in line
        )
        shim.write_text(without_launch_line, encoding="utf-8")
        self.assertIsNone(executor_module._cmd_shim_launch(str(shim)))

    def test_the_shape_claude_actually_has_names_an_executable_not_javascript(self):
        """`npm view @anthropic-ai/claude-code bin` -> `{claude: 'bin/claude.exe'}` (2.1.268):
        the npm package installs a native launcher, so its shim runs that `.exe` directly and
        there is no JavaScript in it anywhere. Measured on a Windows runner in acceptance run
        34613046096, where the first version of this parser found nothing and fell back to
        `cmd.exe` -- on the very host it was written for.
        """
        shim = _install_shim(self.root, "claude-native.cmd")
        kind, program, before, after = executor_module._cmd_shim_launch(str(shim))
        self.assertEqual(kind, "exec")
        self.assertTrue(program.endswith(os.path.join("bin", "claude.exe")))
        self.assertEqual((before, after), ([], []))

    def test_a_shim_naming_an_interpreter_this_machine_does_not_have_is_refused(self):
        """`tests/_fake_cli.py`'s own shape, recorded: `"C:\\Python312\\python.exe"
        "%~dp0fake-cli.py" %*`. That interpreter is not on this machine, so there is nothing to
        launch and the shim is left to `cmd.exe`.
        """
        shim = _install_shim(self.root, "hand-written-python.cmd")
        self.assertIsNone(executor_module._cmd_shim_launch(str(shim)))

    def test_an_interpreter_shim_carries_the_script_the_shim_named(self):
        """The same shape with an interpreter that *is* here -- which is what a Windows runner
        has for this repository's own fake CLIs. The script the shim names travels with it:
        launching the interpreter with the CLI's flags and no script at all is how the first
        version of this parser broke twenty tests on windows-latest.
        """
        interpreter = self.root / "python.exe"
        interpreter.write_text("# stands in for a real interpreter\n", encoding="utf-8")
        script = self.root / "fake-cli.py"
        script.write_text("print('hi')\n", encoding="utf-8")
        shim = self.root / "fake.cmd"
        shim.write_text(
            '@echo off\r\n"%s" "%%~dp0fake-cli.py" %%*\r\n' % interpreter, encoding="utf-8"
        )

        kind, program, before, after = executor_module._cmd_shim_launch(str(shim))
        self.assertEqual(kind, "exec")
        self.assertEqual(Path(program).resolve(), interpreter.resolve())
        self.assertEqual(before, [])
        self.assertEqual([Path(a).resolve() for a in after], [script.resolve()])

        with mock.patch.object(os, "name", "nt"):
            argv, note = executor_module._launch_argv([str(shim), "-p", "--tools", ""])
        self.assertEqual(
            [Path(argv[0]).resolve(), Path(argv[1]).resolve()],
            [interpreter.resolve(), script.resolve()],
        )
        self.assertEqual(argv[2:], ["-p", "--tools", ""])
        self.assertIn("via=program", note)

    def test_a_target_that_is_not_on_this_machine_is_not_returned(self):
        """A shim left behind by an uninstall names a `cli.js` that is gone. Launching `node`
        at a path that does not exist would turn a missing install into a node error.
        """
        shim = _install_shim(self.root, "claude.cmd")
        (self.root / _SHIM_TARGETS["claude.cmd"]).unlink()
        self.assertIsNone(executor_module._cmd_shim_launch(str(shim)))

    def test_an_unreadable_shim_is_not_an_exception(self):
        self.assertIsNone(executor_module._cmd_shim_launch(str(self.root / "nothing-here.cmd")))

    def test_a_batch_variable_this_parser_does_not_understand_is_refused(self):
        shim = self.root / "odd.cmd"
        shim.write_text('@echo off\r\n"%SOMEWHERE%\\cli.js" %*\r\n', encoding="utf-8")
        self.assertIsNone(executor_module._cmd_shim_launch(str(shim)))


class LaunchArgvTest(unittest.TestCase):
    """FR-004: what actually gets launched, and the one line the launch log carries."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.fake_node = self.root / "node"
        self.fake_node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.fake_node.chmod(0o755)

    def _with_node(self):
        """`node` first on PATH, wherever this test happens to be running."""
        return mock.patch.dict(
            os.environ, {"PATH": str(self.root) + os.pathsep + os.environ.get("PATH", "")}
        )

    def test_nothing_changes_off_windows(self):
        shim = _install_shim(self.root, "claude.cmd")
        with mock.patch.object(os, "name", "posix"), self._with_node():
            argv, note = executor_module._launch_argv([str(shim), "-p", "--tools", ""])
        self.assertEqual(argv, [str(shim), "-p", "--tools", ""])
        self.assertIsNone(note)

    def test_a_windows_npm_shim_is_launched_through_node(self):
        shim = _install_shim(self.root, "claude.cmd")
        entry = str((self.root / _SHIM_TARGETS["claude.cmd"]))
        with mock.patch.object(os, "name", "nt"), self._with_node():
            argv, note = executor_module._launch_argv([str(shim), "-p", "--json-schema", "{}"])

        # `node.EXE` on a Windows runner, `node` elsewhere -- `shutil.which` returns the name
        # it resolved, extension and all (measured: tests.yml on windows-latest).
        self.assertTrue(Path(argv[0]).name.lower().startswith("node"), argv[0])
        self.assertEqual(Path(argv[1]).resolve(), Path(entry).resolve())
        self.assertEqual(argv[2:], ["-p", "--json-schema", "{}"])
        self.assertIn("via=node", note)
        self.assertIn("cli.js", note)

    def test_the_shims_node_flags_come_first(self):
        shim = _install_shim(self.root, "copilot.cmd")
        with mock.patch.object(os, "name", "nt"), self._with_node():
            argv, _ = executor_module._launch_argv([str(shim), "-p", ""])
        self.assertEqual(argv[1], "--enable-source-maps")
        self.assertTrue(argv[2].endswith("index.js"))
        self.assertEqual(argv[3:], ["-p", ""])

    def test_an_unparseable_shim_falls_back_to_the_shim_and_says_why(self):
        shim = _install_shim(self.root, "hand-written-python.cmd")
        with mock.patch.object(os, "name", "nt"), self._with_node():
            argv, note = executor_module._launch_argv([str(shim), "-p"])
        self.assertEqual(argv, [str(shim), "-p"])
        self.assertIn("via=cmd.exe", note)
        self.assertIn("neither a JavaScript entry point nor an executable", note)

    def test_a_native_shim_launches_its_executable_directly(self):
        """No `node` in this chain, and no `cmd.exe` either: the shim's own program, run."""
        shim = _install_shim(self.root, "claude-native.cmd")
        with mock.patch.object(os, "name", "nt"), self._with_node():
            argv, note = executor_module._launch_argv([str(shim), "-p", "--json-schema", "{}"])
        self.assertTrue(argv[0].endswith(os.path.join("bin", "claude.exe")))
        self.assertEqual(argv[1:], ["-p", "--json-schema", "{}"])
        self.assertIn("via=program", note)
        self.assertNotIn("via=cmd.exe", note)

    def test_a_native_shim_needs_no_node_at_all(self):
        shim = _install_shim(self.root, "claude-native.cmd")
        with mock.patch.object(os, "name", "nt"), mock.patch.object(
            executor_module.shutil, "which", return_value=None
        ):
            argv, note = executor_module._launch_argv([str(shim), "-p"])
        self.assertTrue(argv[0].endswith("claude.exe"))
        self.assertIn("via=program", note)

    def test_no_node_on_path_falls_back_to_the_shim_and_says_why(self):
        shim = _install_shim(self.root, "claude.cmd")
        with mock.patch.object(os, "name", "nt"), mock.patch.object(
            executor_module.shutil, "which", return_value=None
        ):
            argv, note = executor_module._launch_argv([str(shim), "-p"])
        self.assertEqual(argv, [str(shim), "-p"])
        self.assertIn("via=cmd.exe", note)
        self.assertIn("no 'node' on PATH", note)

    def test_a_binary_that_is_not_a_shim_is_left_alone_on_windows_too(self):
        with mock.patch.object(os, "name", "nt"), self._with_node():
            argv, note = executor_module._launch_argv(["C:\\tools\\claude.exe", "-p"])
        self.assertEqual(argv, ["C:\\tools\\claude.exe", "-p"])
        self.assertIsNone(note)

    def test_the_uppercase_extension_windows_actually_resolves_is_handled(self):
        """`shutil.which` returned `claude.CMD` on the staging runner, not `claude.cmd`."""
        shim = _install_shim(self.root, "claude.cmd")
        upper = shim.with_name("CLAUDE.CMD")
        shim.rename(upper)
        with mock.patch.object(os, "name", "nt"), self._with_node():
            argv, note = executor_module._launch_argv([str(upper), "-p"])
        self.assertTrue(Path(argv[0]).name.lower().startswith("node"), argv[0])
        self.assertIn("via=node", note)

    def test_the_launch_note_is_said_once_per_process(self):
        executor_module._LAUNCH_NOTES_SAID.clear()
        self.addCleanup(executor_module._LAUNCH_NOTES_SAID.clear)
        with mock.patch("builtins.print") as printed:
            executor_module._say_launch_note("KEEL_LAUNCH via=node node=x entry=y shim=z")
            executor_module._say_launch_note("KEEL_LAUNCH via=node node=x entry=y shim=z")
            executor_module._say_launch_note(None)
        self.assertEqual(printed.call_count, 1)


_RESULT_EVENT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "num_turns": 1,
    "permission_denials": [],
    "total_cost_usd": 0.01,
    "structured_output": {"outcome": "COMPLETED", "result": {"statement": "ok"}},
}


@unittest.skipUnless(shutil.which("node"), "no `node` on PATH to run the fake CLI with")
class ThroughTheExecutorsTest(unittest.TestCase):
    """FR-005: both executors, end to end, with the flags that broke on staging.

    A real `node` runs a fake `cli.js` -- the exact shape the fix produces -- so what these
    assert is that every flag and the whole prompt arrive at the program itself, with no batch
    interpreter anywhere between. `--json-schema`'s JSON and `--system-prompt`'s sentence are
    the two arguments `cmd.exe` mangled, so they are the two these check character for
    character.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.addCleanup(self._tmp.cleanup)
        executor_module._LAUNCH_NOTES_SAID.clear()
        self.addCleanup(executor_module._LAUNCH_NOTES_SAID.clear)

    def _install(self, name, responses):
        shim = _install_shim(self.root, name, js_source=_FAKE_CLI_JS)
        self.entry_dir = (self.root / _SHIM_TARGETS[name]).parent
        (self.entry_dir / "responses.json").write_text(json.dumps(responses), encoding="utf-8")
        return shim

    def _records(self):
        return json.loads((self.entry_dir / "records.json").read_text(encoding="utf-8"))

    def test_the_claude_executor_reaches_the_cli_with_every_flag_intact(self):
        self._install(
            "claude.cmd",
            [{"stdout": json.dumps(_RESULT_EVENT) + "\n", "returncode": 0}],
        )
        executor = ClaudeCodeExecutor(binary="claude.cmd", home=self.home, timeout_seconds=30.0)
        request = _request()

        with mock.patch.object(os, "name", "nt"), mock.patch.dict(
            os.environ, {"PATH": str(self.root) + os.pathsep + os.environ.get("PATH", "")}
        ):
            answer = executor.execute(request)

        self.assertEqual(answer, _RESULT_EVENT["structured_output"])

        record = self._records()[0]
        argv = record["argv"]
        schema = json.dumps(
            executor_module._build_envelope_schema(request.request_payload["response_contract"])
        )
        self.assertEqual(argv[argv.index("--json-schema") + 1], schema)
        self.assertEqual(argv[argv.index("--system-prompt") + 1], SYSTEM_PROMPT)
        self.assertIn("--no-session-persistence", argv)
        # The prompt still travels on stdin, whole, as spec 005's amendment left it.
        self.assertIn("the founder's framing text", record["stdin"])
        self.assertGreater(len(record["stdin"].splitlines()), 10)

    def test_the_copilot_executor_reaches_the_cli_with_every_flag_intact(self):
        completed = (_COPILOT_FIXTURES / "completed.jsonl").read_text(encoding="utf-8")
        self._install("copilot.cmd", [{"stdout": completed, "returncode": 0}])
        executor = CopilotExecutor(binary="copilot.cmd", home=self.home, timeout_seconds=30.0)

        with mock.patch.object(os, "name", "nt"), mock.patch.dict(
            os.environ, {"PATH": str(self.root) + os.pathsep + os.environ.get("PATH", "")}
        ):
            answer = executor.execute(
                _request(
                    response_contract={
                        "allowed_outcomes": ["COMPLETED", "NEEDS_INPUT"],
                        "completed_result_schema": {
                            "type": "object",
                            "required": ["summary"],
                            "properties": {"summary": {"type": "string", "maxLength": 400}},
                        },
                    }
                )
            )

        self.assertEqual(answer["outcome"], "COMPLETED")

        record = self._records()[0]
        self.assertEqual(record["execArgv"], ["--enable-source-maps"])
        for tool in ("--excluded-tools=apply_patch", "--excluded-tools=powershell"):
            self.assertIn(tool, record["argv"])
        self.assertIn("SYSTEM", record["stdin"])
        self.assertIn("<<<KEEL-DATA", record["stdin"])

    def test_a_multi_line_prompt_and_a_json_flag_survive_together(self):
        """The two failures in one: a prompt `cmd.exe` would cut at its first newline, and a
        flag `cmd.exe` would mangle at its first `%`, `&` or `|`.
        """
        self._install(
            "claude.cmd",
            [{"stdout": json.dumps(_RESULT_EVENT) + "\n", "returncode": 0}],
        )
        content = "\n".join(
            [
                "LINE-ONE: 100% & then some | pipe",
                'LINE-TWO: "quoted" and ^caret^ and <angle>',
                "LINE-THREE: the magic word is ZEPPELIN",
            ]
        )
        executor = ClaudeCodeExecutor(binary="claude.cmd", home=self.home, timeout_seconds=30.0)
        with mock.patch.object(os, "name", "nt"), mock.patch.dict(
            os.environ, {"PATH": str(self.root) + os.pathsep + os.environ.get("PATH", "")}
        ):
            executor.execute(_request(content=content))

        record = self._records()[0]
        for line in content.splitlines():
            self.assertIn(line, record["stdin"])
        self.assertEqual(
            json.loads(record["argv"][record["argv"].index("--json-schema") + 1]),
            executor_module._build_envelope_schema(
                _request().request_payload["response_contract"]
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
