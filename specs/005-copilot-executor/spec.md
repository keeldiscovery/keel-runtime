# Feature Specification: The second host — `CopilotExecutor`, and which one runs

**Feature Branch**: `005-copilot-executor`

**Created**: 2026-09-09

**Status**: Implemented

**Input**: the design of record, keel-cloud `canon/designs/keel-skill-design.md` (2026-09-08) —
§5 *Two hosts: Claude Code and GitHub Copilot* (§5.3 which host and which executor, §5.4
`CopilotExecutor`, §5.5 the four-part "supported" gate), §9 invariants **C-1..C-12** plus R-2 and
R-3, §12 decisions 8, 9 and 15, §13 **implementation order step 7**, §14 acceptance A-4 and A-11.

This is **step 7 of §13, exactly**. The founder's words are *we need to support both*: Claude Code
is not the host, it is one of two. Today the runtime has one real executor and assumes the machine
it is running on has `claude` on it. This spec gives it a second, gives it a rule for choosing, and
makes it say out loud which it chose and why.

**It depends on nothing and may run in parallel with steps 1–6.** It changes no wire shape, adds no
outcome key (decision 15), and leaves the scripted and stub executors exactly as they are (C-12).

## Scope

`keel_runtime/executor.py`, `keel_runtime/config.py`, `keel_runtime/cli.py`, `README.md`, three new
test modules and one new fixture directory. **Out of scope, by name**: the skill's own `--host`
detection table (keel-connect-skill spec `003-bundled-runtime`, another repository's — this spec
only accepts the flag the skill will pass); `HOST={claude,copilot}` on `make instruction-eval` and
the pinned-model measurement (keel-e2e-eval spec `014-copilot-executor`, §13 **step 12**, the only
step that spends the founder's money); the acceptance workflow (§13 **step 11**); `CLOUD_BASE_URL`'s
real value (§13 **step 8**).

## User Scenarios & Testing

### User Story 1 - A run that is not authenticated says so, in words that were observed (Priority: P1)

**This is task 1, and it is C-6.** `ClaudeCodeExecutor` recognises an authentication failure by
matching `"not logged in"` in the CLI's own reply. Copilot's equivalent had never been observed:
the machine the design was written on had a stored credential that beat a bogus
`COPILOT_GITHUB_TOKEN`, and what *was* seen with an invalid token was a `session.error` carrying
`CAPIError: 400 The requested model is not supported.` — an authentication failure wearing a model
failure's clothes. Matching on that would be matching on a lie.

So before any of this spec's code was written, three genuinely unauthenticated runs were produced
on a clean machine — a fresh `COPILOT_HOME` so no stored credential could win — and what they
actually do was recorded.

**Why this priority**: an executor that mislabels "you are logged out" as "the LLM is unreachable"
sends a founder to the wrong remedy, and every other requirement here can be written around
whatever the measurement says. This one has to be measured first or it cannot be written at all.

**Independent Test**: the three recordings are in the repository, and a test asserts the code's
markers against the recordings rather than against a restatement of them.

**Acceptance Scenarios**:

1. **Given** a fresh `COPILOT_HOME` and no token of any kind, **When** `copilot -p …
   --output-format json` runs, **Then** it exits **1**, writes **nothing at all to stdout** — not
   one line of JSONL, and no `session.error` anywhere — and writes
   `Error: No authentication information found.` to stderr.
2. **Given** the same and `COPILOT_GITHUB_TOKEN` holding a classic `ghp_` PAT, **Then** exit 1,
   empty stdout, and `Error: Classic Personal Access Tokens (ghp_) are not supported by Copilot.`
3. **Given** the same and a well-formed but invalid fine-grained token, **Then** exit 1, empty
   stdout, and `Error: Authentication token found but could not be validated.`
4. **Given** any of those three recordings replayed, **When** `CopilotExecutor.execute` reads it,
   **Then** it raises `ExecutorAuthFailure` carrying the observed first line.
5. **Given** a `session.error` the code does not recognise — including the CAPIError above — **When**
   it is read, **Then** the failure is `ExecutorUnavailable`, **never** `ExecutorAuthFailure`.

**The finding**: the design expected the marker inside the JSONL. It is not there. **CLI 1.0.83
fails before the session starts**, so there is no session to carry an error, and the observed
marker is on **stderr** with an empty stdout. The code reads stderr *and* every `session.error`
together, so the marker keeps working if a later CLI moves it.

---

### User Story 2 - A job runs through Copilot and comes back the same shape (Priority: P1)

A founder whose machine has `copilot` and not `claude` says "keel connect", approves the device,
and Keel works. `poller` cannot tell which host answered: the same `{outcome, questions?|result?}`
dict, the same three exceptions, the same per-job log.

**Why this priority**: it is the feature. Everything else here is how it is chosen and how it is
proved honest.

**Independent Test**: the recorded JSONL of a real closed-shape run replays into `execute` and
yields the validated answer, with `jsonschema` absent.

**Acceptance Scenarios**:

1. **Given** the recorded JSONL of a real completed run, **When** `execute` reads it, **Then** the
   answer is the last `assistant.message` whose `data.phase == "final_answer"`, parsed as JSON and
   validated against the job's own `response_contract`.
2. **Given** a run whose answer arrived inside a ` ```json ` fence — measured, even when the prompt
   asked for none — **Then** the fence is stripped rather than the answer refused.
3. **Given** a run whose final answer is prose, **Then** one recovery pass runs quoting what was
   wrong, and if that fails too the job is `InvalidResponse`.
4. **Given** any Copilot job, **When** `last_envelope` is written, **Then** it carries `num_turns`
   (the count of `assistant.turn_end`) and `premium_requests`, and **no `total_cost_usd` at all**
   — absent, not zero (C-7).
5. **Given** the whole path run with `jsonschema` unimportable, **Then** every assertion above still
   holds and the **stdlib subset validator** is what did the validating (R-2).

---

### User Story 3 - The closed shape is proved for this job, not claimed once (Priority: P1)

The model that reads a stranger's answer must have no tool with which to act on an instruction
hidden in it. On the Claude path that is `--tools ""`. On Copilot, `--available-tools` with an
empty value was measured to be *ignored* — 18 tools survived it — and only `--excluded-tools` with
every name enumerated reaches `tool_count: 0`. **An enumeration rots the day Copilot ships a new
tool.**

**Why this priority**: this is the strongest form of the words-are-words guarantee anywhere in
Keel — stronger, today, than the Claude path's, because it is checked per job.

**Independent Test**: a verbatim recording of a run with an incomplete enumeration fails, and its
answer is never returned.

**Acceptance Scenarios**:

1. **Given** a run whose own `session.usage_checkpoint` reports `tool_count: 0`, **Then** the job
   proceeds.
2. **Given** a run reporting any non-zero `tool_count`, **Then** the job fails **before its answer
   is used**, whatever the answer says and whatever the exit code says.
3. **Given** a run that reported no `session.usage_checkpoint` at all, **Then** it fails the same
   way: an unverifiable closed shape is not a closed shape.

**It rotted during this spec.** A run that dropped two names from the enumeration left `apply_patch`
available to the model and **exited 0** with a well-formed answer. That recording is in the
repository as `tool-count-not-zero.jsonl`, and it is the whole argument for C-1.

---

### User Story 4 - The runtime says which executor it chose, and why (Priority: P2)

A founder debugging a job, and a referee reading a bundle, both need to know not only *what* ran
but *why it was picked*. One line at startup, into the log the skill is already reading, in the
same machine-readable family as `KEEL_USER_CODE=`.

**Why this priority**: without it, every selection bug is invisible and every measurement is
unattributable. With it, `source=ambiguous-path` in a log is a complete explanation.

**Independent Test**: the three line shapes, asserted against a faked `PATH`.

**Acceptance Scenarios**:

1. **Given** a resolved executor, **Then** `keel connect` prints
   `KEEL_EXECUTOR=<name> source=<source>` with `binary=` and `version=` when they are cheap to
   have.
2. **Given** both CLIs on `PATH` and nothing else deciding, **Then** the line says
   `source=ambiguous-path` and names the flag that would settle it.
3. **Given** a chosen executor whose CLI is not on `PATH`, **Then** a second line
   `KEEL_EXECUTOR_UNAVAILABLE=<name>` is printed and **the runtime still connects** — the device is
   authorized either way and each job reports `EXECUTOR_UNAVAILABLE` on its own.
4. **Given** a Copilot run with no pinned `--model`, **Then** the line says `model=auto` out loud,
   because a run that did not pin a model measured the router, not a model (C-5).

---

### User Story 5 - `keel status` agrees with the startup line (Priority: P2)

**Independent Test**: `status` as a real subprocess under each selection input.

**Acceptance Scenarios**:

1. **Given** any resolution, **Then** `executor` and `executor_on_path` are present in **both**
   `status` shapes and describe what the selection order actually resolved.
2. **Given** `KEEL_EXECUTOR=claude-code`, **Then** `status` reports `claude` — the canonical name —
   while still accepting the alias as input (C-12).
3. **Given** a Copilot-hosted machine with no `claude` anywhere, **Then** `executor_on_path` is
   `true`. **A `claude_on_path` boolean is never built**, because it would read `false` on a
   healthy runtime, which is a lie about health (C-10).
4. `status` still never exits non-zero and never makes a network call (R-4).

## Requirements

- **FR-001** `CopilotExecutor`, behind the existing `Executor` ABC, returning the same
  `{outcome, questions?|result?}` dict and raising the same `ExecutorUnavailable`,
  `ExecutorAuthFailure`, `ExecutorTimeout`. `build_prompt`, `_prompt_sections`, `_render_prompt`
  and `_build_envelope_schema` are **shared unchanged** — the prompt is the runtime's, not the
  host's, or the instruction eval measures two different things (C-8).
- **FR-002** The invocation, one process per job:
  `copilot -p <prompt> --excluded-tools=<name> …(one flag per name) --disable-builtin-mcps
  --no-custom-instructions --no-ask-user --no-remote --no-remote-export --no-auto-update
  --no-color --output-format json --log-level none --max-ai-credits <n≥30> -C <job_dir>
  [--model <slug>]`, with `cwd` the same empty `$KEEL_HOME/jobs/<job_id>/`. **There is no
  `--json-schema`, no `--system-prompt`, no turn limit and no timeout flag on this CLI**, and none
  is passed. `--excluded-tools` is variadic in the CLI's parser, so it is passed **one flag per
  name** or it would swallow the flags that follow it.
- **FR-003** The two sections Claude gets as flags move into the prompt text, **above TASK and
  outside the KEEL-DATA fence** — they are the executor addressing the model, not source material
  it must never follow: `SYSTEM` carrying the fixed `SYSTEM_PROMPT` verbatim, and `RESPONSE`
  carrying `_build_envelope_schema(response_contract)` as JSON with one instruction. The rendered
  body below them is **byte-identical** to what the Claude path sends.
- **FR-004** **The prompt is one argv element through a list `subprocess.run`, never a shell
  string** (C-2), so the nonce fence and every character of a stranger's answer survive. Above a
  512 KB guard the executor raises `InvalidResponse` **naming the size**, rather than letting
  `ARG_MAX` surface as an `ExecutorUnavailable` nobody can act on.
- **FR-005** Reading the result back, in order, every step a refusal if it fails: parse stdout as
  JSONL with the existing `_parse_stream_events`; **any `session.error` is a failure whatever the
  exit code says** (C-3); assert this job's own `tool_count` is 0 (C-1) **before the answer is
  used**; take the last `assistant.message` whose `data.phase == "final_answer"` (a tool-calling
  turn emits an `assistant.message` with empty content, so "the last assistant message" is the
  wrong rule); strip an optional ` ```json ` fence; `json.loads`; require an object; validate
  through the **same `response_validator` the Claude path's poller uses**.
- **FR-006** A validation failure becomes `last_schema_error`, and spec `002-words-are-words`
  FR-011's **one** recovery pass runs unchanged, quoting it. `last_envelope`,
  `last_request_sections`, `last_events` and `last_schema_error` are exposed after every call,
  exactly as `ClaudeCodeExecutor` exposes them, so `poller` logs both hosts the same way without
  knowing which it has.
- **FR-007** `last_envelope` carries `num_turns` from the count of `assistant.turn_end` and
  `premium_requests` from `usage.premiumRequests`, and **`total_cost_usd` is absent, not zero**
  (C-7) — Copilot reports premium requests and the runtime never invents a dollar figure it was
  not given.
- **FR-008** **The exit code is not a success signal** (C-3). Measured against 1.0.83: a run whose
  every tool was denied and whose task therefore failed exits **0**; an unauthenticated run exits
  **1** with no JSONL at all. Success is decided by the JSONL.
- **FR-009** `ExecutorAuthFailure` is raised only on an **observed** marker (C-6), matched
  case-insensitively against stderr and every `session.error` together. The three observed strings
  are in the code with their measurement beside them. Anything else is `ExecutorUnavailable`, which
  fails the safe way.
- **FR-010** The timeout is the runtime's, because the CLI has none:
  `subprocess.run(timeout=self.timeout_seconds)` at the same `DEFAULT_JOB_TIMEOUT_SECONDS` (300 s)
  the Claude path uses — the job is the same job — raising `ExecutorTimeout`.
- **FR-011** **Each executor's environment allow-list is its own** (C-4). One mechanism, two
  argument pairs: the common set (`PATH`, `HOME`, `USER`, `LANG`, `TMPDIR`, `TERM`, every `LC_*`)
  reaches both; `ClaudeCodeExecutor` adds `ANTHROPIC_*` and `CLAUDE_*`; `CopilotExecutor` adds
  `COPILOT_*`, `GH_TOKEN`, `GITHUB_TOKEN` and `GH_HOST`. **Neither passes the other's**, and
  neither passes `PYTHONPATH` or any other interpreter variable (R-3) — `PYTHONPATH` is how the
  skill reaches the runtime and has no business inside a host CLI.
- **FR-012** `_EXECUTORS` gains `copilot`, and `claude` becomes the canonical name for the Claude
  path. **`claude-code` is a permanent accepted alias** resolved by one `canonical_executor_name`
  in `config.py` (C-12). `scripted` and `stub` are untouched.
- **FR-013** `config.resolve_executor(args, file_config)` returns `(name, source)` implementing the
  whole of §5.3:
  1. **explicit** — `--executor` > `KEEL_EXECUTOR` > `$KEEL_HOME/config.json["executor"]` — that
     one, **always, even if its CLI is missing**, because a founder who names an executor is
     answering the question and the missing CLI is reported per job;
  2. **host** — `--host`, then the environment's markers (`COPILOT_AGENT_SESSION_ID` non-empty or
     `COPILOT_CLI == "1"` → copilot; `CLAUDECODE == "1"` → claude; `AI_AGENT` starting
     `github_copilot` → copilot, `claude-code` → claude). **Exactly one answer, take it; two
     different answers, take NEITHER** and fall through;
  3. **PATH** — exactly one of `copilot`/`claude` present → that one;
  4. both present and nothing above decided → `claude`, `source=ambiguous-path`;
  5. neither present → `claude`, `source=default`.

  `source` is one of `flag`, `env`, `config`, `host`, `path`, `ambiguous-path`, `default`.
- **FR-014** `connect` accepts `--host {claude,copilot,auto}`, default `auto` — the skill runs the
  detection table itself and passes it through. It is a **host signal**: step 2, below every
  explicit term, above the environment markers. `status` and `disconnect` do not take it; neither
  runs a job. **No outcome shape changes** (decision 15).
- **FR-015** `connect` accepts `--copilot-model`, resolving `--copilot-model` >
  `KEEL_COPILOT_MODEL` > `config.json["copilot_model"]` > unpinned. It is **unpinned by default**
  and the reason is measured, not assumed: see the Assumptions below.
- **FR-016** `keel connect` prints the `KEEL_EXECUTOR=` line of §5.3 immediately after
  `KEEL_ENVIRONMENT=`, and a `KEEL_EXECUTOR_UNAVAILABLE=` line beneath it when the chosen
  executor's CLI is absent. The version is probed best-effort with a one-second timeout: a founder
  gets a version when it is cheap and the line without one when it is not, and **a connect is never
  held up for a decoration**.
- **FR-017** `status`'s `executor` and `executor_on_path` report what `resolve_executor` resolved,
  in both shapes (C-10).
- **FR-018** Tests: the C-6 recordings as fixtures with their assertions; the selection order as a
  **table**; recorded JSONL for a completed job, a refused job, a malformed result, an auth failure
  and a timeout; `_build_env` allow-listing asserted for **both** executors, and against what a
  real child process actually received. The whole Copilot path is exercised with `jsonschema`
  absent (R-2). The existing 257 tests stay green.

### Key Entities

- **executor** — the runtime's abstraction for making one inference call. A host *has* an executor;
  an executor is not a host.
- **source** — *why* this executor was chosen. The same vocabulary `resolve_runtime` uses in the
  skill, for the same reason: show why, not only what.
- **the closed shape** — a host CLI invocation with no tool the model can reach. Asserted per job
  on the Copilot path, from that job's own `session.usage_checkpoint`.

## Success Criteria

- **SC-001** `python -m pytest` green on **3.9** and on the newest interpreter present, with
  neither `keyring` nor `jsonschema` installed. **257 tests before this feature; more after.**
- **SC-002** C-6 is closed: a genuinely unauthenticated `copilot` run exists as a recording in this
  repository, its exact `session.error` (there is none) and exit code (1) are written down, and the
  code's markers are asserted against the recordings.
- **SC-003** Every requirement above has at least one test, and every invariant C-1..C-12 is cited
  by id in the code comment, the requirement and the test that checks it.
- **SC-004** No wire shape changes, no outcome key is added, and `scripted`/`stub` need no edit.
- **SC-005** The three `KEEL_EXECUTOR=` line shapes are produced by a real `keel connect` on the
  founder's Mac.

## Assumptions

- **`--model` could not be pinned on the founder's machine, and that is measured, not assumed.**
  On 2026-09-09, CLI 1.0.83 rejected **every** slug offered to `--model` — `gpt-5.1`, `gpt-4.1`,
  `gpt-5-mini`, `gpt-5-codex`, `claude-sonnet-4.5`, `claude-haiku-4.5`, and even
  `mai-code-1.1-flash`, the model its own router had just chosen — each with
  `Model "…" from --model flag is not available.` The account's catalogue exposes auto-routed
  models only. So the pin is **configurable and applied only when set**, rather than a constant
  that would make every run on that machine fail, and an unpinned run prints `model=auto` so it can
  never be silently mistaken for a measured one. **C-5 is therefore satisfied by mechanism here and
  closed by measurement in §13 step 12** (keel-e2e-eval `014-copilot-executor`), on an account
  whose catalogue allows a pin. This is a finding, and findings are the deliverable.
- **`--excluded-tools` is a superset by design.** Two of the twenty names (`rg`, and on some
  configurations others) are reported back by 1.0.83 as
  `Unknown tool name in the tool excludedlist`, which is a harmless `session.info`. Naming a tool
  that does not exist costs nothing; failing to name one that does costs the guarantee — and C-1's
  per-job check is what actually holds the line.
- **The `result` event exists and carries `exitCode` and `usage.premiumRequests`.** Measured. It is
  read when present and the envelope simply omits what it did not carry.
- **The skill's half of `--host` is another repository's** (keel-connect-skill spec
  `003-bundled-runtime`). This spec accepts the flag and behaves correctly whether or not anything
  ever passes it.
- **Two existing test assertions change, and only because this feature changes what they assert**:
  `tests/test_config.py`'s default-executor test and `tests/test_cli_status.py`'s two exact-payload
  comparisons now read `claude` rather than `claude-code`, because the canonical name changed. The
  alias still resolves; nothing else in the suite is touched.
- **Migration is nil**: no production data, no release. A `config.json` carrying
  `"executor": "claude-code"` keeps working, by the alias.
