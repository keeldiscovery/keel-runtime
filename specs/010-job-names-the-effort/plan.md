# Implementation Plan: The job names the effort

**Branch**: `010-job-names-the-effort` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

## Summary

**Five edits and one new test module.** The effort travels the road the model already travels, one
step behind it, and every decision below is "do what `model` does".

| # | Edit | File |
|---|---|---|
| 1 | `InferenceRequest.effort`, beside `model` | `keel_runtime/executor.py` |
| 2 | `_effort_for`, the twin of `_model_for`, wired in `_handle_job` | `keel_runtime/poller.py` |
| 3 | `_build_argv(..., effort)` → `--effort <level>`, last | `keel_runtime/executor.py` |
| 4 | `_invoke(..., effort)` threaded to all three call sites | `keel_runtime/executor.py` |
| 5 | The prohibition comment, README, version | `config.py`, `README.md`, `__init__.py`, `pyproject.toml` |

## Technical Context

Python 3.9+, stdlib only, no new dependency. `python -m pytest -q` is the gate; CI runs it on
ubuntu 3.9–3.13 plus macOS and Windows 3.9/3.13.

## Decisions

### Decision 1 — the flag is appended after `--model`, and the `if` is separate

```python
] + (["--model", model] if model else []) + (["--effort", effort] if effort else [])
```

Two independent tails rather than one branch, because the two are independent: a job may name a
model with no effort (`reading` on the `light` tier, every Codex and Copilot job), and — although
the cloud's table refuses to produce it — an effort with no model is not this function's business to
reject. Appending last keeps every pre-0.6.0 argv byte-identical, which is what `SC-003` asserts.

### Decision 2 — every `_invoke` gets it, including the retry (FR-005)

Three call sites: the first pass, the unpinned retry, the recovery pass. The retry passes
`model=None` **and `effort=effort`**: the refusal named a model, so the model is what is dropped.

### Decision 3 — no validation, and the reason is that two parties already do it

keel-cloud's `ModelRouting` refuses a word outside `low|medium|high|xhigh|max` at startup, with the
whole table in hand; the CLI refuses one at the flag. A check here would be a third opinion that can
only ever disagree with one of them.

### Decision 4 — the environment variable is not touched

`CLAUDE_CODE_EFFORT_LEVEL` keeps passing through `_build_env`'s `CLAUDE_` prefix as it always has.
This spec adds no name to the allow-list and removes none: an operator who exports it still gets
what they always got, and a job that names an effort now gets the flag as well — the CLI's own
precedence decides, and that is the CLI's business. The runtime grows no opinion about it and no
knob for it (FR-007).

### Decision 5 — nothing new on the completion report

`execution` stays `{host, host_version, model_requested, model_used, retried_unpinned}`. See spec
A-4: the cloud sent the effort, so the cloud has it, and a sixth key would need a change in two
other repositories to be worth anything.

## Phase plan

| Phase | What | Gate |
|---|---|---|
| 1 | Spec, plan, tasks | committed before any Python moves |
| 2 | The fixture: `claude --help`'s effort line, recorded | `pytest -q` |
| 3 | The request, the poller, the argv, the three call sites | `pytest -q` |
| 4 | Tests, README, version 0.6.0 | `pytest -q` green |
