# Tasks: The effort reaches Codex and Copilot

**Input**: [spec.md](./spec.md), [plan.md](./plan.md); keel-cloud spec `055-openai-pins`,
`canon/drafts/codex-terra-luna-screen-2026-10-03.md` §6, `canon/designs/model-routing-design.md`
§4/§5/§6/§8; this repository's spec 010.

**Rules**: stdlib only; no new dependency; no effort knob anywhere in this runtime; every host
behaviour claim is measured and recorded as a fixture; nothing is substituted for a word a host
cannot take.

**Gate**: `python3 -m pytest -q` green on Python 3.9.

## Phase 1 — the spec

- [x] T001 `specs/011-effort-for-codex-copilot/spec.md`.
- [x] T002 `specs/011-effort-for-codex-copilot/plan.md`.
- [x] T003 `specs/011-effort-for-codex-copilot/tasks.md` — this file.

## Phase 2 — what was measured

- [x] T004 `tests/fixtures/codex/exec-config-help.txt`: the `-c, --config <key=value>` entry of
  `codex exec --help` on 0.154.0, verbatim, with its `MANIFEST.json` row naming the key
  (`model_reasoning_effort`), the probe that measured it accepted, and the catalogue ladder per
  model as read on 2026-10-03.
- [x] T005 `tests/fixtures/copilot/effort-help.txt`: the `--effort, --reasoning-effort <level>`
  entry of `copilot --help` on 1.0.83, verbatim, with its `MANIFEST.json` row saying no call was
  made.

## Phase 3 — the runtime

- [x] T006 `keel_runtime/executor.py`: `COPILOT_EFFORT_LADDER`, `CODEX_EFFORT_LADDER`,
  `_require_effort_on_ladder` (raises `ExecutorUnavailable` naming the word and the ladder);
  both exported in `__all__`.
- [x] T007 `CodexExecutor._build_argv(..., effort)`: `-c model_reasoning_effort=<level>` after
  `-m`, only when named, checked against the Codex ladder; the docstring says why there is no
  `--effort` and why the check is here.
- [x] T008 `CopilotExecutor._build_argv(..., effort)`: `--effort <level>` after `--model`, only
  when named, checked against the Copilot ladder.
- [x] T009 Both `_invoke(..., effort)`; both `execute` read `request.effort` as the Claude executor
  does and pass it to the first pass, the unpinned retry (model `None`, effort kept) and the
  recovery pass.
- [x] T010 `InferenceRequest.effort`'s comment and `ClaudeCodeExecutor._build_argv`'s comment no
  longer say the other two hosts carry none.

## Phase 4 — tests, docs, version

- [x] T011 `tests/test_codex_executor.py`, `tests/test_copilot_executor.py`: `_request(effort=)`.
- [x] T012 `tests/test_effort_routing.py`: spec 010's `TheOtherTwoHostsGetNothingTest` replaced by
  the v8 reading; per host — the recorded fixture against the constant; the argv with and without;
  byte-identity with 0.6.0; every ladder word accepted and only those; the flag through the fake
  CLI; the unpinned retry keeping it; a word off the ladder failing by name with no process
  spawned. `ThereIsNoEffortKnobTest` unchanged.
- [x] T013 `README.md`: the v8 wire example, the three-ladder table, the two argv blocks.
- [x] T014 Version **0.7.0** in `keel_runtime/__init__.py` and `pyproject.toml`.
- [x] T015 Gate: `python3 -m pytest -q` green. Commit; merge `--no-ff` into master; push.

## What is deliberately not in this file

- Any effort knob (spec 010 FR-007).
- Any change to the poller — `_effort_for` already reads every host.
- Any validation on the Claude executor (spec 010 FR-008 stands).
- A per-model Codex ladder, or reading the catalogue at runtime (spec A-2).
- A keel-connect-skill release — the plugin vendors 0.5.1; re-bundling is the founder's call.
