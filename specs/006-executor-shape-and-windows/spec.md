# Feature Specification: The envelope the model is held to, and a Windows launch without `cmd.exe`

**Feature Branch**: `executor-shape-and-windows`

**Created**: 2026-09-11

**Status**: Implemented

**Input**: two staging measurements, not a design document. keel-e2e-eval runs **34602329238** and
**34607630153** (the Ubuntu Claude cells) for the envelope; runs **34566001772** and
**34607630153** (the Windows Claude cells) for the launch. The design of record that both sit
under is keel-cloud `canon/designs/keel-skill-design.md` §3 (the bundled runtime) and
`words-are-words-design.md` §L1-L2 (the closed shape and the prompt), neither of which changes
here.

Two fixes to `keel_runtime/executor.py`, each with its own failure already recorded on a real
runner. Neither changes a wire shape, an outcome key, or anything a founder types.

## Scope

`keel_runtime/executor.py`, `.github/workflows/acceptance.yml`, `README.md`, one new test module,
one new fixture directory. **Out of scope, by name**: `keel-connect-skill` and its release (a
separate step); `response_validator.py`'s own rules, which are the thing being *agreed with*, not
changed; keel-cloud's contracts; the instruction eval.

## User Scenarios & Testing

### User Story 1 - A COMPLETED answer with no result is refused while the model can still answer (Priority: P1)

Measured twice, on two different days, on staging. The model answered:

```json
{"outcome": "COMPLETED"}
```

The CLI **accepted** it -- correctly, because the `--json-schema` the runtime handed it listed
`result` under `properties` and named only `outcome` in `required`. The runtime then refused the
same answer a moment later with `COMPLETED requires a 'result'`, which is `validate_response`'s
own rule (FR-019). The one recovery pass (spec `002-words-are-words` FR-011) did not land, and the
job failed.

Two enforcers, two different rules, and the looser one is the one the model was shown. The model
was never told the thing it got wrong.

**Why this priority**: it is a whole job lost, it happened twice, and the remedy costs nothing --
the runtime already knows the rule, it just was not writing it into the schema.

**Independent Test**: `_build_envelope_schema`'s output and `validate_response` are run over the
same table of answers and must agree answer for answer, including `{"outcome": "COMPLETED"}`.

**Acceptance Scenarios**:

1. **Given** a contract allowing `COMPLETED` and `NEEDS_INPUT`, **When** the envelope schema is
   built, **Then** the COMPLETED branch requires `result` and the NEEDS_INPUT branch requires
   `questions`, and neither branch permits the other's key.
2. **Given** the answer both staging runs produced, **When** it is checked against that schema,
   **Then** it satisfies no branch -- the refusal now happens inside the CLI's own loop, where a
   further turn is still available.
3. **Given** a refusal that names a missing key, **When** the recovery pass is built, **Then** the
   prompt names that key and asks for it, rather than telling the model to cut a field in half.

### User Story 2 - The Claude and Copilot CLIs start on Windows (Priority: P1)

Measured on staging. `shutil.which("claude")` resolves to `C:\npm\prefix\claude.CMD` -- the npm
install shape, and the only shape a Windows founder has. Launching it means launching `cmd.exe`:
Windows' own loader dispatches a `.cmd` through the command interpreter by its extension,
`shell=True` or not. The job then died one of two ways:

* **exit 255, no output at all**, or
* `The filename, directory name, or volume label syntax is incorrect.`

`--system-prompt`'s sentence and `--json-schema`'s JSON are full of the characters a batch file
treats as syntax (`%`, `&`, `|`, `<`, `>`, `^`, `"`), and no quoting on the Python side survives a
second round of batch parsing on the other side. Spec `005`'s amendment moved the **prompt** to
stdin for exactly this reason; the flags stayed on the old road.

**Why this priority**: on Windows, with the real CLI, **no job can complete at all**. It is not a
degradation, it is the whole host.

**Independent Test**: npm's own `cmd-shim` generator's output is recorded as a fixture, parsed on
whatever OS the suite runs on, and both executors are driven end to end through a real `node`
against a fake `cli.js`.

**Acceptance Scenarios**:

1. **Given** a resolved binary ending `.cmd`/`.CMD` on Windows, **When** the shim names a
   JavaScript entry point and `node` is on `PATH`, **Then** `[node, <entry>, *args]` is launched
   and `cmd.exe` is not in the chain.
2. **Given** a shim whose target has shebang flags (`#!/usr/bin/env node --enable-source-maps`,
   which npm copies into the shim), **When** it is launched, **Then** those flags go to `node`.
3. **Given** a shim with no readable JavaScript entry, or a machine with no `node`, **When** the
   CLI is launched, **Then** the shim is launched exactly as before and one line in the launch log
   names the shim and the reason.
4. **Given** macOS or Linux, **When** anything is launched, **Then** nothing changes at all.

### User Story 3 - CI proves the Windows Claude executor before the plugin ships (Priority: P2)

`acceptance.yml` has proven a multi-line prompt through `CopilotExecutor` on all three operating
systems since spec `005`. The Claude executor -- the default host, and the one that failed on
Windows -- had no equivalent. The plugin release was about to ship a runtime whose Windows Claude
path nothing had ever run.

**Independent Test**: the acceptance run this commit triggers, `model-driven half` on
`windows-latest`.

**Acceptance Scenarios**:

1. **Given** this repository's Claude secret, **When** `acceptance.yml` runs, **Then** a three-line
   prompt goes through `ClaudeCodeExecutor` on ubuntu, macOS **and** windows, and each asserts the
   model saw three lines and echoed the word that appears only on the third.
2. **Given** the same run on Windows, **Then** the step log carries the `KEEL_LAUNCH` line saying
   which road the launch took.

## Requirements

### Functional Requirements

- **FR-001**: `_build_envelope_schema` MUST build one branch per allowed outcome and combine them
  with `anyOf` under a top-level `type: "object"`; each branch names its outcome as a `const`,
  requires the key that outcome must carry (`result` for `COMPLETED`, `questions` for
  `NEEDS_INPUT`), and sets `additionalProperties: false`. An outcome the runtime has no rule for
  requires the outcome alone. A contract naming no outcome at all keeps the flat envelope
  (nothing to branch on). **The top-level `type` is not decoration**: the CLI hands this document
  to the API as the `StructuredOutput` tool's `input_schema`, and a tool schema without one is
  `400 tools.0.custom.input_schema.type: Field required` -- measured on all three operating
  systems in acceptance run 34613046096, where a bare `anyOf` failed every job it touched.
- **FR-002**: when a refusal says a key is missing -- Ajv's `must have required property 'x'`, or
  `response_validator`'s own `COMPLETED requires a 'result'` / `NEEDS_INPUT requires a non-empty
  questions[] array` -- the recovery prompt MUST name that key and ask for it. Every other refusal
  keeps the existing "cut the named field to half its length" wording verbatim.
- **FR-003**: on Windows, a resolved binary ending `.cmd`/`.bat` MUST be **read**, and the
  program named on its launch line (the line carrying `%*`) resolved against the shim's own
  directory (`%dp0%`/`%~dp0`). Both of npm's shapes MUST be handled: a JavaScript entry point
  (`node` plus any flags the shim passes it, which npm copies from the target's shebang) **and a
  native executable the shim runs directly**. The path is parsed out of the shim's text, never
  guessed from a package name. A target that is not a file on this machine is not a program.
- **FR-004**: both executors MUST launch what the shim would have launched -- `[node,
  *node_flags, <entry>, *args]` for the JavaScript shape, `[<exe>, *args]` for the native one.
  Otherwise (nothing recognisable in the shim, or no `node` for a JavaScript one) they MUST
  launch the shim as before, and the runtime MUST print one line naming the shim and the reason
  -- once per process per shape.
- **FR-005**: nothing changes off Windows, and nothing changes for a binary that is not a shim.
- **FR-006**: `response_validator` is unchanged. Its stdlib subset never sees the envelope schema
  -- the envelope's rules are explicit Python in `validate_response`, and the `completed_result_schema`
  it does validate is unchanged -- so the Copilot path behaves exactly as before.
- **FR-007**: `acceptance.yml` MUST run a three-line prompt through `ClaudeCodeExecutor` on all
  three operating systems, gated on the Claude secret the same way the existing Claude steps are.

### Key Entities

- **envelope schema** -- the `--json-schema` document. Claude Code turns it into a client-side
  tool (`StructuredOutput`) and validates the model's tool input against it with Ajv.
- **npm `.cmd` shim** -- a generated batch file whose last line runs one JavaScript file with
  `node`. Generated by npm's `cmd-shim`; recorded verbatim in `tests/fixtures/windows/`.

## Success Criteria

- **SC-001**: `python -m pytest -q` green on 3.9 and 3.13, with neither `keyring` nor
  `jsonschema` installed.
- **SC-002**: the answer `{"outcome": "COMPLETED"}` satisfies no branch of a built envelope, and
  the schema and `validate_response` agree over a table of answers.
- **SC-003**: both executors' flags and prompt arrive at a real program's argv/stdin intact when
  the resolved binary is a recorded npm shim and `os.name` is `nt`.
- **SC-004**: the acceptance run on `windows-latest` completes both three-line-prompt steps.

## Measurement notes (what was run, and what was not)

**No paid model call was made locally for this spec.** The `--json-schema` question was settled by
pointing `ANTHROPIC_BASE_URL` at a local recording server and reading what Claude Code 2.1.268
actually sends:

* `--json-schema <doc>` becomes a tool named `StructuredOutput` whose `input_schema` is `<doc>`
  **verbatim** -- nothing is stripped, `strict: true` is not set, and `output_config` carries only
  `effort`. The API is therefore not enforcing this schema at all.
* The enforcement is the CLI's own **Ajv (JSON Schema 2020-12)** validation of that tool's input;
  a failure is handed back to the model as the `Output does not match required schema` tool result
  the runtime already reads.
* All four candidate documents (flat, `allOf` of `if`/`then`, `anyOf`, `oneOf`) were accepted and
  travelled verbatim. Ajv honours all three conditional forms.
* **`anyOf` was chosen** because it is the only one of the three inside Anthropic's own documented
  structured-output subset -- the subset that would apply the day a CLI passes this document to
  the API as a strict tool schema or an `output_config.format`. `oneOf` and `if`/`then` are not
  supported keywords there.

The npm shim fixtures are npm's own generator's output, produced by calling
`node_modules/npm/node_modules/cmd-shim` directly (see `tests/fixtures/windows/MANIFEST.json`),
not written by hand.

**What the first acceptance run corrected.** Run 34613046096 is part of this feature's record, not
a footnote to it. It failed, twice over, and both failures were things no local test could have
told us:

* `API Error: 400 tools.0.custom.input_schema.type: Field required` on all three operating
  systems. The `anyOf` document is passed straight through as a *tool schema*, and the API
  requires `type` on one. Adding `type: "object"` above the `anyOf` is the whole fix (FR-001).
* `KEEL_LAUNCH via=cmd.exe shim=C:\npm\prefix\claude.CMD -- no JavaScript entry point could be
  read out of this shim` on windows-latest. `@anthropic-ai/claude-code`'s npm package installs a
  **native launcher** (`npm view ... bin` -> `{claude: 'bin/claude.exe'}`, 2.1.268), so its shim
  contains no JavaScript at all and a `.js`-only parser fell back to `cmd.exe` on the exact host
  this feature exists for. `@github/copilot` in the same run took the new road correctly:
  `KEEL_LAUNCH via=node node=...node.EXE entry=...\@github\copilot\npm-loader.js
  shim=C:\npm\prefix\copilot.CMD`, and its three-line prompt step passed on windows-latest.
  The parser now handles both of npm's shapes (FR-003).

Both corrections are in this feature's second commit, and the acceptance run after it is the
proof that replaces this one.
