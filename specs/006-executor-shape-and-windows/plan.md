# Implementation Plan: The envelope the model is held to, and a Windows launch without `cmd.exe`

**Branch**: `executor-shape-and-windows` | **Date**: 2026-09-11 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md) (FR-001..007, SC-001..004); staging runs 34602329238, 34607630153,
34566001772; keel-cloud `canon/designs/keel-skill-design.md` §3.

## Summary

One file changes: `keel_runtime/executor.py`. Two small, separable things live in it.

**The envelope.** `_build_envelope_schema` stops building one permissive object and starts building
one branch per allowed outcome. The rule it encodes is not a new rule -- it is
`response_validator.validate_response`'s, moved to where the model can still act on it. The pairing
lives in one dict (`_OUTCOME_REQUIRED_KEY`) so the two enforcers cannot drift apart again, and a
test runs both over the same answers and asserts they agree.

**The launch.** A new `_launch_argv` sits in front of `subprocess.run` inside
`_run_with_prompt_on_stdin` -- the one place both executors already share, so neither host can get
a different rule. Off Windows, and for any binary that is not a `.cmd`/`.bat`, it returns its
argument unchanged and says nothing.

Neither change touches the wire, the outcomes, the poller, or `response_validator`.

## Technical Context

**Language/Version**: Python **3.9** floor through 3.13. `from __future__ import annotations` is
already at the top of `executor.py`, so `str | None` annotations stay legal at 3.9 (checked with
`/usr/bin/python3`, 3.9.6).

**Primary Dependencies**: none added. `re` joins the module's stdlib imports.

**External CLI**: Claude Code **2.1.268** for the `--json-schema` measurement; npm 11's bundled
`cmd-shim` for the fixtures. Neither is called by the suite.

**Testing**: `unittest` modules under `tests/`, run with `python -m pytest`. **375 tests before
this feature**, 408 after. The new `tests/test_windows_launch.py` runs on every OS: the Windows
branch is reached by monkey-patching `os.name`, which is sound here because `shutil.which` and
`subprocess` both branch on `sys.platform` instead.

**Constraints**: standard library only under `keel_runtime/`; no wire change; no new outcome key;
existing assertions not weakened.

**Scale/Scope**: one runtime file, one workflow, one README section, one new test module, four
new fixture files.

## Two decisions worth writing down

### `anyOf`, and why not `oneOf` or `if`/`then`

Measured rather than assumed (spec's *Measurement notes*). All three forms travel to the CLI
verbatim and all three are honoured by the Ajv the CLI validates with, so the tie is broken by what
survives a change on the other side: `anyOf` is in Anthropic's documented structured-output subset
and the other two are not. If a future Claude Code hands this document to the API as a strict tool
schema, `anyOf` keeps working and `oneOf`/`if`-`then` become a 400.

`oneOf` would also be *wrong* in a way `anyOf` is not, the day two outcomes share a shape: `oneOf`
demands exactly one match, so two identical branches would refuse a correct answer. `anyOf` cannot
develop that fault.

### The top-level `type`, which only a real run could teach

`anyOf` alone is valid JSON Schema and Ajv is happy with it. The API is not: the document becomes a
tool's `input_schema`, and `400 tools.0.custom.input_schema.type: Field required` was the answer on
every operating system. `type: "object"` now sits above the `anyOf` as well as inside every branch.
The local measurement (a recording server) could show what the CLI *sends*; only the acceptance run
could show what the API *accepts*, which is why the run is the gate and not a formality.

### Parse the shim; never guess the path -- and launch what it runs, JavaScript or not

`node_modules\@anthropic-ai\claude-code\cli.js` is knowable from the package name, and hard-coding
it would work today on one host and be a lie about the other -- and it would have been a lie about
*this* one: `claude`'s npm package installs `bin/claude.exe`, a native launcher, so its shim names
no JavaScript at all. npm writes the real path into the shim; the shim is on disk; reading it is
both shorter and true. The parser therefore reads the shim's **launch line** (the one carrying
`%*`) and handles both of npm's shapes: `node` plus a `.js`, or an `.exe` run directly. The parser only accepts a **quoted** token
ending in `.js`/`.cjs`/`.mjs` (the generated shim also contains `SET PATHEXT=%PATHEXT:;.JS;=;%`,
which a looser parser reads as a file name), expands `%dp0%`/`%~dp0` and nothing else, and returns
a path only if it is a file on this machine.

`os.path`, not `pathlib`, inside those helpers: `pathlib.Path` picks its flavour from `os.name` at
construction, so a test that patches `os.name` to `"nt"` on a Mac gets a `WindowsPath` it cannot
instantiate. `os.path` is fixed at interpreter start and does the same job.

## Project Structure

```
keel_runtime/executor.py                     _OUTCOME_REQUIRED_KEY, _envelope_branch,
                                             _build_envelope_schema, _missing_key,
                                             _recovery_section, _expand_shim_path,
                                             _cmd_shim_target, _launch_argv, _say_launch_note
tests/test_windows_launch.py                 new: FR-003..005, both executors
tests/test_executor.py                       EnvelopeSchemaTest, AjvAgreementTest,
                                             RecoveryNamesTheMissingKeyTest; the exact-argv
                                             assertion updated to the new schema, still exact
tests/test_copilot_executor.py               the same two rules on the other host
tests/fixtures/windows/{claude,copilot,compiled-tool}.cmd + MANIFEST.json
.github/workflows/acceptance.yml             the ClaudeCodeExecutor three-line step
README.md                                    the envelope, and the Windows launch
```

## Risks

* **A Windows machine with no `node`.** Possible (a `claude.cmd` installed by something that
  bundles its own node). It falls back to today's behaviour, which is the behaviour that failed --
  but it says so in the launch log, which is the difference between a known limitation and a
  mystery.
* **A future npm shim template.** The parser is written against a *shape* (a quoted `.js` on the
  launch line), not a version, and fails closed to the old behaviour with a reason.
* **A contract with an outcome the runtime has no rule for.** Its branch requires the outcome
  alone -- the same latitude `validate_response` gives it.
