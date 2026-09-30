# Tasks: The job names the effort

**Input**: [spec.md](./spec.md), [plan.md](./plan.md); keel-cloud spec `047-sonnet-5-5-medium`,
`canon/designs/model-routing-design.md` §4/§5/§6/§8, run `20260930T024851Z-instructions`.

**Rules**: stdlib only; no new dependency; no effort knob anywhere in this runtime; every host
behaviour claim is measured and recorded as a fixture.

**Gate**: `python -m pytest -q` green on Python 3.9.

## Phase 1 — the spec

- [x] T001 `specs/010-job-names-the-effort/spec.md`.
- [x] T002 `specs/010-job-names-the-effort/plan.md`.
- [x] T003 `specs/010-job-names-the-effort/tasks.md` — this file.

## Phase 2 — what was measured

- [x] T004 `tests/fixtures/claude/effort-help.txt`: the `--effort` line of `claude --help` on
  2.1.284, recorded verbatim, with its `MANIFEST.json` row — a flag nobody recorded is not a flag.

## Phase 3 — the runtime

- [x] T005 `keel_runtime/executor.py`: `InferenceRequest.effort`, beside `model`, with the comment
  that says where it comes from and that there is no other source.
- [x] T006 `keel_runtime/poller.py`: `_effort_for`, the twin of `_model_for`; wired in
  `_handle_job`.
- [x] T007 `keel_runtime/executor.py`: `ClaudeCodeExecutor._build_argv(..., effort)` appends
  `--effort <level>` last, and `_invoke(..., effort)` threads it.
- [x] T008 `keel_runtime/executor.py`: all three `_invoke` call sites in `execute` pass the effort —
  the first pass, the **unpinned retry** (model `None`, effort kept) and the recovery pass.
- [x] T009 `keel_runtime/config.py`: extend spec 009's "there is no model knob here" comment to say
  the same of the effort, and why.

## Phase 4 — tests, docs, version

- [x] T010 `tests/test_effort_routing.py`: the argv with and without; the four ways of meaning "no
  flag"; the byte-identical pre-0.6.0 argv; the unpinned retry keeping the effort; Codex and Copilot
  unchanged; an unknown word passed through.
- [x] T011 `tests/test_executor.py`: the full-argv equality test updated, not relaxed.
- [x] T012 `README.md`: the key beside `model`, the flag beside `--model`, and the certified pair.
- [x] T013 Version **0.6.0** in `keel_runtime/__init__.py` and `pyproject.toml`.
- [x] T014 Gate: `python -m pytest -q` green. Commit.

## What is deliberately not in this file

- Any effort knob: no flag, no `KEEL_*` variable, no config key (FR-007).
- Any validation of the effort word (FR-008).
- Any new flag for Codex or Copilot (FR-006) — neither CLI's argv has one to give.
- Any new key on the completion report (spec A-4).
