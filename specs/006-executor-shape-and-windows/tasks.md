# Tasks: The envelope the model is held to, and a Windows launch without `cmd.exe`

**Input**: [spec.md](spec.md) (FR-001..007, SC-001..004), [plan.md](plan.md).

**Rules**: standard library only under `keel_runtime/`; no wire change and no new outcome key; no
existing assertion weakened; `keel-connect-skill` untouched (its release is a separate step); no
paid model call from this machine -- the acceptance run is the proof.

**Gate**: `python -m pytest -q` green, with neither `keyring` nor `jsonschema` installed.

## Phase 1: Measure first

- [x] T001 **Which schema form does Claude Code actually enforce?** Settled without spending a
      model call: `ANTHROPIC_BASE_URL` pointed at a local recording server, four candidate
      documents sent, the request bodies read back. **Found**: `--json-schema <doc>` becomes a
      client-side tool `StructuredOutput` whose `input_schema` is `<doc>` **verbatim**; no
      `strict: true`, no `output_config.format`, nothing stripped -- so the API enforces none of
      it and the CLI's own **Ajv 2020-12** does. All four documents travelled verbatim. Ajv
      honours `anyOf`, `oneOf` and `if`/`then` alike.
- [x] T002 **Which form should we therefore send?** `anyOf` -- the only one of the three in
      Anthropic's documented structured-output subset, so the envelope survives the day a CLI
      passes it to the API as a strict tool schema. Recorded in `_build_envelope_schema`'s
      docstring beside the measurement, not in a commit message.
- [x] T003 **What does an npm shim actually look like?** Not recalled -- generated, by calling
      npm's own `cmd-shim` (npm 11) against three targets: a `node` shebang, a
      `node --enable-source-maps` shebang, and a target with no shebang at all. The three
      `.cmd` files are `tests/fixtures/windows/`, with `MANIFEST.json` saying how each was made.

## Phase 2: The envelope (FR-001, FR-002, FR-006)

- [x] T004 `_OUTCOME_REQUIRED_KEY` + `_envelope_branch` + the new `_build_envelope_schema`: one
      branch per allowed outcome, `anyOf` of the branches, `additionalProperties: false` on each.
      One allowed outcome is one object, not an `anyOf` of one. No allowed outcome keeps the flat
      envelope.
- [x] T005 `_missing_key` / `_recovery_section`: Ajv's `must have required property 'x'` and
      `response_validator`'s own two phrasings both name a key; every other refusal keeps the
      existing wording verbatim. Both executors call `_recovery_section`.
- [x] T006 Verify `response_validator` needs no change: its stdlib subset is only ever applied to
      `result` against `completed_result_schema` -- the envelope's own rules are explicit Python
      in `validate_response` -- so it never sees an `anyOf` and the Copilot path is unchanged.
- [x] T007 Tests: `EnvelopeSchemaTest` (branch shape, the staging answer refused, the two
      enforcers agreeing answer for answer), `AjvAgreementTest` (the same table through a real
      validator where one is installed; skipped in the shipped configuration),
      `RecoveryNamesTheMissingKeyTest`, and the Copilot path's two. `test_argv_is_exactly_the_
      closed_shape` updated to the new schema -- still asserted in full.

## Phase 3: The launch (FR-003, FR-004, FR-005)

- [x] T008 `_expand_shim_path` / `_cmd_shim_target`: read the shim, take the quoted
      `.js`/`.cjs`/`.mjs` on the launch line, expand `%dp0%`/`%~dp0` against the shim's own
      directory, keep the node flags before it, and return it only if it is a file. `os.path`
      throughout, so the parser is testable under a patched `os.name`.
- [x] T009 `_launch_argv` + `_say_launch_note`, called from `_run_with_prompt_on_stdin` so both
      executors take the same road. Fall back to the shim with a reason; one line per process.
- [x] T010 `tests/test_windows_launch.py`: the parser against the recorded shims (including the
      `%PATHEXT:;.JS;=;%` trap and a target that has been uninstalled), `_launch_argv`'s four
      outcomes, and both executors end to end through a **real `node`** against a fake `cli.js`,
      asserting `--json-schema`'s JSON and `--system-prompt`'s sentence arrive character for
      character and the prompt still arrives whole on stdin.

## Phase 4: Proof and prose (FR-007)

- [x] T011 `acceptance.yml`: "A three-line prompt through ClaudeCodeExecutor reaches the model
      whole", beside the Copilot step, on all three operating systems, gated on the Claude secret
      the same way, asserting COMPLETED **with** a `result`. `actionlint` clean.
- [x] T012 README: the envelope's new shape and why, and the Windows launch and its fallback.
- [x] T013 `python -m pytest -q` green on 3.13 and on 3.9 (`/usr/bin/python3`), no extras
      installed.
- [x] T014 Merge `--no-ff` into master, push, and watch the acceptance run it triggers -- the
      Windows Claude cell is the one this feature exists for.

## Phase 5: What that run corrected

- [x] T015 **The envelope needed a top-level `type`.** Acceptance run 34613046096, all three
      operating systems: `API Error: 400 tools.0.custom.input_schema.type: Field required`. The
      document is passed through as a tool schema and the API requires `type` on one. `anyOf` now
      sits under `type: "object"`. Asserted structurally and in the exact-argv test.
- [x] T016 **`claude`'s Windows shim has no JavaScript in it.** Same run, windows-latest:
      `KEEL_LAUNCH via=cmd.exe shim=C:\npm\prefix\claude.CMD -- no JavaScript entry point could
      be read out of this shim`. `npm view @anthropic-ai/claude-code bin` ->
      `{claude: 'bin/claude.exe'}` (2.1.268): the package installs a native launcher. The parser
      now reads the shim's launch line and handles both of npm's shapes -- `node` + `.js`, or the
      `.exe` directly. `@github/copilot` took the new road correctly in that same run
      (`via=node ... npm-loader.js`) and its windows-latest step passed, which is what says the
      shim-reading half was right and only its vocabulary was too narrow.
- [x] T017 Fixtures regenerated to match: `claude-native.cmd` (npm's no-shebang shape, the real
      `bin/claude.exe` path) replaces the invented `compiled-tool.cmd`, and
      `hand-written-python.cmd` carries the genuine fallback case. `tests.yml`'s two
      windows-latest failures (`node.EXE` != `node` -- `shutil.which` returns the extension it
      resolved) fixed in the assertion, not in the code.
- [x] T018 Merge again, push, and watch the acceptance run that replaces 34613046096.
