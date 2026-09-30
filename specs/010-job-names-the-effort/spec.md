# Feature Specification: The job names the effort — the certified combination reaches a founder's own CLI

**Feature Branch**: `010-job-names-the-effort` (branch `010-job-names-the-effort`)

**Created**: 2026-09-30

**Status**: Draft

**Input**: keel-cloud spec `047-sonnet-5-5-medium` and run of record
`20260930T024851Z-instructions` (`keel-cloud/canon/drafts/sonnet-5-5-medium-run-of-record-2026-09-30.md`),
against `keel-cloud/canon/designs/model-routing-design.md` §4 (the table and its new `efforts`
block), §5 (the wire's seventh key), §6 (the runtime's one rule) and §8 (no cloud-side translation);
and this repository's own spec `009-model-routing`, whose shape this one copies exactly.

## Scope

`keel_runtime/executor.py`, `keel_runtime/poller.py`, `README.md`, one new test module, one new
fixture recording. **Out of scope**: the `efforts` block and the `effort` key's production
(keel-cloud spec 047, already implemented), the eval's own pinning (keel-e2e-eval), the skill's
bundled runtime refresh (keel-connect-skill, `make runtime`).

## The one sentence

**A job may now name an effort level for this host the same way it names a model — `request_payload
["effort"][<host_key>]` beside `request_payload["model"][<host_key>]` — and `ClaudeCodeExecutor`
passes it to the CLI as `--effort <level>`; no key, no flag, exactly as with the model; and Codex
and Copilot pass nothing new, because neither CLI's argv has an effort flag to pass it to.**

## Why this exists, in one paragraph

Until this spec the cloud could tell a founder's own CLI *which model* to run and not *how hard to
think*. That was fine while the certificate was a model. It is not fine now: run
`20260930T024851Z-instructions` certified **`claude-sonnet-5-5` at effort `medium`** — one pair, not
one model — and the Claude Code CLI's own default effort is `xhigh`. So an own-AI founder handed the
model without the effort runs a combination nobody certified, and pays for it: measured over the 63
assumption job-runs of that run against the 2026-09-13 record, `xhigh` is **3.7× the thinking** and
**2.4× the wall clock** of `medium`, for five marks `medium` already holds. One flag closes that.

## What was measured before anything was written (2026-09-30, the founder's Mac)

1. **The flag exists and takes the ladder.** `claude --help` on **2.1.284**:
   `--effort <level>    Effort level for the current session (low, medium, high, xhigh, max)`.
   Five words, the same five the API's `output_config.effort` takes and the same five
   `keel-cloud`'s `ModelRouting.EFFORT_LADDER` validates. **Recorded as a fixture**
   (`tests/fixtures/claude/effort-help.txt`), because a flag nobody recorded is not a flag.
2. **The environment variable is not the mechanism here.** `CLAUDE_CODE_EFFORT_LEVEL` does reach the
   CLI — `_build_env`'s `CLAUDE_` prefix allow-lists it through from whatever the operator exported
   — and that is **exactly why it is the wrong mechanism for a per-job value**: it is process-wide,
   it is inherited by anything else the process spawns, and keel-e2e-eval had to write a
   `judge_env()` that strips it by name to stop a subject's setting silently scoring its own run.
   A per-job flag on a per-job argv cannot do that.
3. **Codex and Copilot have no counterpart wired.** `CopilotExecutor._build_argv` and
   `CodexExecutor._build_argv` carry no effort or reasoning flag at all; Codex's own
   `-c model_reasoning_effort=…` has never been passed by this runtime, and the only note about it
   in this codebase records that its plan's default is `none`. **Nothing is invented for them.**

## Requirements

- **FR-001** `InferenceRequest` gains `effort: "str | None" = None`, beside `model`, defaulting to
  `None`.
- **FR-002** `poller._effort_for(executor, request_payload)` reads
  `request_payload["effort"][<host_key>]` and answers the stripped string when it is a non-empty
  string, else `None` — the same four ways of meaning "no flag" `_model_for` already has: no key, a
  non-object value, no entry for this host, a value that is not a non-empty string.
- **FR-003** `poller._handle_job` populates `InferenceRequest.effort` from it.
- **FR-004** `ClaudeCodeExecutor._build_argv` appends `--effort <level>` when, and only when, an
  effort was given, **after** the model flag, so an argv without an effort is byte-identical to one
  built before this spec.
- **FR-005** The effort is passed on **every** invocation of a job, including the unpinned retry and
  the recovery pass. A model refusal is a refusal of the *model*; the effort was not what was
  refused, and dropping it would silently run the retry at the CLI's default.
- **FR-006** `CopilotExecutor` and `CodexExecutor` pass nothing new. Their `_build_argv` signatures
  and argv are untouched.
- **FR-007** The runtime keeps **no** effort knob: no flag, no `KEEL_*` variable, no config key. The
  effort comes with the job and from nowhere else — spec 009's rule for the model, applied to the
  second half of the same pin, and written into `config.py`'s existing prohibition comment.
- **FR-008** An unknown effort word is **passed through**, not validated. The cloud's table refuses
  a word outside the ladder at startup, and the CLI refuses one at the flag; a third opinion here
  would only disagree with one of them the day the ladder grows.
- **FR-009** README documents the key beside `model` and the flag beside `--model`.
- **FR-010** Version **0.6.0**, in `keel_runtime/__init__.py` and `pyproject.toml`.

## Success Criteria

- **SC-001** `_build_argv(schema)` has no `--effort`; `_build_argv(schema, "claude-sonnet-5-5",
  "medium")` ends `--model claude-sonnet-5-5 --effort medium`.
- **SC-002** A job whose payload carries `{"effort": {"claude": "medium"}}` produces an argv with
  `--effort medium`; the same payload seen by a Codex or Copilot executor produces no new flag.
- **SC-003** A payload with no `effort` key, an `effort` that is not an object, an `effort` with no
  entry for this host, and an `effort` whose value is blank all produce an argv **byte-identical**
  to the pre-0.6.0 one.
- **SC-004** An unpinned retry after a model refusal still carries `--effort`.
- **SC-005** `python -m pytest -q` green on Python 3.9+; the full-argv equality test is updated
  rather than relaxed.

## Assumptions and judgement calls

- **A-1 — A flag, not the environment variable.** Both reach the CLI. The flag is per-job, is
  visible in the job's own argv, cannot leak into a sibling process, and needs no allow-list entry.
  The variable is process-wide and is the thing keel-e2e-eval's judge already has to defend itself
  against. A per-job value belongs on a per-job argv.
- **A-2 — The effort survives the unpinned retry (FR-005).** The retry exists because the CLI
  refused a *model* by name. Dropping the effort there would answer a model refusal by also
  changing how hard the model thinks — two changes for one refusal, and the second one silent.
- **A-3 — No validation here (FR-008).** Two parties already refuse a bad word, one at startup with
  the whole table in hand and one at the flag itself. A third check in the middle can only be wrong
  in a new way.
- **A-4 — Nothing new is reported back on completion.** `execution` stays the five keys spec 009
  defined. The effort the cloud sent is a fact the cloud already has; adding a sixth key would need
  a keel-cloud change to keep it and a keel-e2e-eval fixture change to match, for a value nobody has
  asked to read back. Named here so the next person knows it was a decision.
