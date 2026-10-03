# Implementation Plan: The effort reaches Codex and Copilot

**Branch**: `011-effort-for-codex-copilot` | **Date**: 2026-10-03 | **Spec**: [spec.md](./spec.md)

## Summary

**One module, two fixtures, one test module, README, version.** Spec 010's road, extended to the
two hosts it stopped short of, with one difference each host earns: a per-host ladder, checked
here, because Codex's CLI cannot check it for us.

| # | Edit | File |
|---|---|---|
| 1 | `CODEX_EFFORT_LADDER`, `COPILOT_EFFORT_LADDER`, `_require_effort_on_ladder` | `keel_runtime/executor.py` |
| 2 | `CodexExecutor._build_argv(..., effort)` → `-c model_reasoning_effort=<level>`, last | `keel_runtime/executor.py` |
| 3 | `CopilotExecutor._build_argv(..., effort)` → `--effort <level>`, last | `keel_runtime/executor.py` |
| 4 | Both `_invoke(..., effort)`; both `execute` read `request.effort` and pass it at all three call sites | `keel_runtime/executor.py` |
| 5 | The two recordings and their `MANIFEST.json` rows | `tests/fixtures/codex/exec-config-help.txt`, `tests/fixtures/copilot/effort-help.txt` |
| 6 | Tests, README, version 0.7.0 | `tests/test_effort_routing.py`, `tests/test_{codex,copilot}_executor.py` (`_request(effort=)`), `README.md`, `__init__.py`, `pyproject.toml` |

## Technical Context

Python 3.9+, stdlib only, no new dependency. `python3 -m pytest -q` is the gate; CI runs it on
ubuntu 3.9–3.13 plus macOS and Windows 3.9/3.13. The poller is not touched.

## Decisions

### Decision 1 — the override is appended after `-m`, and the `if` is separate

```python
if model:
    argv += ["-m", model]
if effort:
    _require_effort_on_ladder("codex", effort, CODEX_EFFORT_LADDER)
    argv += ["-c", f"model_reasoning_effort={effort}"]
```

Spec 010 Decision 1, on this host: two independent tails, effort last, so every pre-0.7.0 argv is
byte-identical. The refusal sits inside the `if`, so a job with no effort never meets it.

### Decision 2 — one ladder per host, as constants, each tied to its fixture by a test

Three CLIs, three vocabularies: Claude `low|medium|high|xhigh|max`; Copilot `none|minimal|low|
medium|high|xhigh|max`; Codex `low|medium|high|xhigh` as the catalogue's intersection. A shared
list would be wrong for every host in a different way. Each constant lives beside the executor it
serves, and `test_effort_routing.py` reads the recording back against it so the two cannot drift
apart silently.

### Decision 3 — refuse here on the two OpenAI hosts; keep Claude's pass-through

Spec A-2/A-3/A-6. The refusal is `ExecutorUnavailable` raised from `_build_argv`, which both
`_invoke`s call before `_run_with_prompt_on_stdin`, so nothing is spawned; the poller's existing
`except ExecutorUnavailable` reports it on that job as `LLM_UNAVAILABLE`.

### Decision 4 — every pass carries it

`execute` reads the effort once, beside `_begin_model_report`, and passes it to the first pass,
the unpinned retry (`model=None, effort`) and the recovery pass — the three call sites spec 010
threaded on the Claude executor, mirrored.

### Decision 5 — nothing on the completion report, no knob, no poller change

Spec 010 A-4 and FR-007 stand; `ThereIsNoEffortKnobTest` is unchanged and still green.

## Phase plan

| Phase | What | Gate |
|---|---|---|
| 1 | Spec, plan, tasks | committed with the change |
| 2 | The two fixtures and their manifest rows | `pytest -q` |
| 3 | The ladders, the refusal, the two argvs, the six call sites | `pytest -q` |
| 4 | Tests, README, version 0.7.0 | `pytest -q` green |
