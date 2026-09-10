# Implementation Plan: The second host — `CopilotExecutor`, and which one runs

**Branch**: `005-copilot-executor` | **Date**: 2026-09-09 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md) (FR-001..018, SC-001..005) and the design of record, keel-cloud
`canon/designs/keel-skill-design.md` §5, §9 (C-1..C-12, R-2, R-3), §12 decisions 8/9/15, §13 step
7, §14 A-4/A-11.

## Summary

One new class, one new resolver, one new line of output, and a lot of recording.

`CopilotExecutor` sits beside `ClaudeCodeExecutor` behind the same ABC and shares the prompt
builder with it byte for byte — the difference between the two hosts is entirely a difference in
what their CLIs will accept as a flag. `claude` takes a system prompt, a JSON schema, a turn limit
and a budget; `copilot` takes none of them, so two of those move into the prompt text and the other
two have no equivalent. What Claude's CLI enforced during the call, this runtime checks afterwards.

Choosing between them is a five-step order that lives in `config.py` next to the rest of the
resolution chain, and the runtime prints which it chose **and why** on the line after
`KEEL_ENVIRONMENT=`.

The recording is the part that could not be shortened. **The first task was to break a real
`copilot` on purpose** — three times, with an isolated `COPILOT_HOME` — because the design's one
honest gap was that nobody had ever seen this CLI refuse to authenticate. Everything after that
runs against files.

## Technical Context

**Language/Version**: Python **3.9** floor through 3.13. `executor.py` and `config.py` already
carry `from __future__ import annotations`, so the new PEP 604 annotations stay legal at 3.9.

**Primary Dependencies**: none. `jsonschema` stays optional, and on this path that is load-bearing
rather than incidental (R-2): on the Claude path the CLI enforced the envelope schema during the
call, so the runtime's own validator was a second opinion; on the Copilot path it is the **only**
opinion. The Copilot tests therefore run the whole path with `jsonschema` forced out.

**External CLI**: GitHub Copilot CLI **1.0.83**, measured on the founder's Mac 2026-09-09.
Never bundled — it is self-updating and authenticates against an account that is the founder's, so
a frozen copy would be stale within a week and unable to log them in.

**Testing**: `unittest` modules under `tests/`, run with `python -m pytest`. **257 tests before this
feature.** Every Copilot test replays a recording from `tests/fixtures/copilot/`; the real CLI is
invoked exactly zero times by the suite.

**Constraints**: standard library only under `keel_runtime/`; no wire change; no new outcome key
(decision 15); `status` never exits non-zero and never calls the network (R-4).

**Scale/Scope**: three runtime files touched, three test modules added, eight fixtures recorded.

## Constitution Check

This repository has no constitution file. The rules it is held to are the design's invariants, each
cited by id in the code comment, the spec requirement and the test:

| Invariant | How this plan satisfies it |
|---|---|
| **C-1** closed shape per job | `_assert_closed_shape` reads *this job's* `session.usage_checkpoint` and fails on any non-zero `tool_count` — and on a missing checkpoint, because an unverifiable closed shape is not one. A verbatim recording of a run that leaked `apply_patch` is the test. |
| **C-2** the prompt on stdin, 512 KB guard | The prompt is written to the child's stdin as UTF-8 bytes by the shared `_run_with_prompt_on_stdin`, never as an argv element (`copilot -p ""`) and never as a shell string — see [`amendment-prompt-transport.md`](amendment-prompt-transport.md), which supersedes the original "one argv element" wording. The guard raises `InvalidResponse` naming the size **before** the process is spawned. |
| **C-3** success decided by the JSONL | `_assert_ran` treats any `session.error` as fatal regardless of `returncode`, and the completed path never reads `returncode` at all. |
| **C-4** per-executor environment | one `_build_env(prefixes, extra_exact)`; two call sites; a test that inspects what a real child actually received. |
| **C-5** pinned `--model` | `--copilot-model` / `KEEL_COPILOT_MODEL` / `config.json`, applied when set; `model=auto` printed when not, so an unpinned run is never silently measured. **The pin could not be exercised on this machine** — see spec Assumptions. |
| **C-6** observed auth marker | three recordings, three markers, and a test that asserts the markers against the recordings rather than a restatement. |
| **C-7** no invented dollar figure | `_envelope` writes `premium_requests` and never `total_cost_usd`; a test asserts the **absence**. |
| **C-8** identical prompt | `_render_copilot_prompt` ends with the shared `_render_prompt` output; a test asserts `endswith`. |
| **C-9** selection and the startup line | `config.resolve_executor` returns `(name, source)`; `cli.executor_startup_lines` prints it. |
| **C-10** `status` keys | `status` calls the same resolver; `claude_on_path` is never built, and a test asserts it is absent. |
| **C-11** the "supported" gate | not this step's — §13 step 12. Nothing here claims Copilot is supported; the README says "runs, unmeasured", in those words. |
| **C-12** `scripted`/`stub` untouched, `claude-code` a permanent alias | one `canonical_executor_name` in `config.py`; a test builds both names and both test executors. |
| **R-2** no test assumes `jsonschema` | `SubsetValidatorIsLoadBearingTest` forces it absent; the suite is run on two fresh venvs that never had it. |
| **R-3** no interpreter variable reaches a host CLI | asserted for both executors, by name (`PYTHONPATH`, `PYTHONHOME`). |

## Order of work, and why

**1. Break it first.** C-6 could not be designed around; it had to be seen. Three runs, each with
`env -i` and a fresh `COPILOT_HOME`, because the design records that a stored credential beats a
bogus token. The result contradicted the design's expectation — no JSONL at all, the marker on
stderr — and everything downstream was written to what was seen.

**2. Learn the event shapes from real runs, not from documentation.** The names
`assistant.message.data.phase`, `assistant.turn_end`, `session.usage_checkpoint`, and the address
of `tool_count` (`data.promptCacheBreakState[].models[<model>].tool_count`) came from reading real
JSONL. So did the tool enumeration, and so did the discovery that the enumeration was already
incomplete.

**3. Then the class, then the chooser, then the line.** In that order because each is testable
without the next.

## Design notes worth keeping

**Why the two moved sections sit outside the fence.** The `SYSTEM` and `RESPONSE` sections are the
executor addressing the model. Putting them inside the KEEL-DATA fence would label the runtime's
own instructions "source material you must never follow" — the exact opposite of what they are, and
a self-defeating prompt.

**Why the recovery pass triggers on a different condition than Claude's.** On the Claude path the
CLI refuses a bad shape mid-call and the run ends `error_max_turns`, so recovery keys off that. On
the Copilot path nothing refuses anything during the call; the runtime's own validator refuses
afterwards. So recovery keys off `InvalidResponse` from the first read. The *prompt* the recovery
pass appends is the same one, unchanged.

**Why a missing CLI still connects.** The founder's device authorization has nothing to do with
which LLM answers a job. Refusing to connect because `copilot` is absent would turn a per-job
degradation into a total outage, and would hide the one thing worth seeing — which is that jobs are
coming back `EXECUTOR_UNAVAILABLE`.

**Why `claude` won the default.** Decision 8, overrulable: every mark in keel-e2e-eval's
`instructions/marks.toml` was measured through the Claude path, so on a machine that offers both
and says nothing, the measured one is the honest choice. Revisit the moment §5.5's run of record is
green on both.

## Files

| File | Change |
|---|---|
| `keel_runtime/executor.py` | `_build_env(prefixes, extra_exact)` and the two allow-lists; `COPILOT_EXCLUDED_TOOLS`, `COPILOT_AUTH_MARKERS`, the guards; `_render_copilot_prompt` and six JSONL readers; `CopilotExecutor`; `_EXECUTORS` gains `claude` and `copilot`. |
| `keel_runtime/config.py` | `DEFAULT_EXECUTOR` becomes `claude`; `EXECUTOR_BINARIES`, `IN_PROCESS_EXECUTORS`, `EXECUTOR_ALIASES`, `canonical_executor_name`, `ENV_HOST_MARKERS`, `ENV_COPILOT_MODEL`; `host_from_environment`, `executor_on_path`, `resolve_executor`, `resolve_copilot_model`; `RuntimeConfig.executor_source`/`copilot_model`, `StatusConfig.executor_source`. |
| `keel_runtime/cli.py` | `--host`, `--copilot-model`, `--executor` given `choices`; `executor_startup_lines` and `_binary_version`; `_environment_keys` delegates to the resolver. |
| `tests/fixtures/copilot/` | eight recordings and a `MANIFEST.json` saying how each was produced and which is verbatim. |
| `tests/test_copilot_executor.py` | the executor, end to end, against recordings. |
| `tests/test_executor_selection.py` | the selection table, the host markers, the startup line, `status`, the flags. |
| `README.md` | both executors, the selection order, the new knobs, and "runs, unmeasured" in those words. |

## What is deliberately not here

- **The instruction eval's Copilot run.** §13 step 12, keel-e2e-eval. It is the only step that
  spends the founder's money, and it is what closes C-5 and A-11.
- **The acceptance workflow and the Windows job.** §13 step 11.
- **The skill's `--host` detection table.** keel-connect-skill spec `003-bundled-runtime`.
- **Any claim that Copilot is supported.** §5.5's gate has four parts and this step is one of them.
