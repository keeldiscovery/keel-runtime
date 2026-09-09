# Tasks: The second host — `CopilotExecutor`, and which one runs

**Input**: [spec.md](spec.md) (FR-001..018, SC-001..005), [plan.md](plan.md), and keel-cloud
`canon/designs/keel-skill-design.md` §5, §9, §13 step 7.

**Rules**: standard library only under `keel_runtime/`; the scripted and stub executors untouched
(C-12); no wire change and no new outcome key (decision 15); `status` never exits non-zero and
never calls the network (R-4). Out of scope by name: the instruction eval's Copilot run and the
pinned-model measurement (keel-e2e-eval `014`, §13 step 12), the acceptance workflow (§13 step 11),
the skill's own `--host` table (keel-connect-skill `003-bundled-runtime`).

**Gate**: `python -m pytest` green on Python 3.9 and on the newest interpreter present, with
neither `keyring` nor `jsonschema` installed.

## Phase 1: Measure first — C-6 and the event shapes

- [x] T001 **C-6, the spec's first task.** Produce a genuinely unauthenticated `copilot` run on a
      clean machine and record its exact `session.error` and exit code. Three runs, each `env -i`
      with a fresh `COPILOT_HOME` (a stored credential beats a bogus token, which is why the design
      had never seen this): no token at all; a classic `ghp_` PAT; a well-formed but invalid
      `github_pat_` token.
      **Found — and it contradicts the design's expectation.** All three: **exit code 1**,
      **stdout completely empty — no JSONL, and therefore no `session.error` at all** — and one
      message on **stderr**:
      `Error: No authentication information found.` /
      `Error: Classic Personal Access Tokens (ghp_) are not supported by Copilot.` /
      `Error: Authentication token found but could not be validated.`
      CLI 1.0.83 fails *before the session starts*, so there is no session to carry an error. The
      three stderr files are in `tests/fixtures/copilot/`.
- [x] T002 Record the closed-shape event vocabulary from real runs rather than documentation:
      `session.start`, `session.auto_mode_resolved`, `session.info`, `session.tools_updated`,
      `assistant.turn_start`, `assistant.message` (with `data.phase`), `assistant.message_delta`,
      `assistant.reasoning`, `assistant.turn_end`, `session.usage_checkpoint`, `assistant.idle`,
      `result`. **`tool_count` lives at
      `data.promptCacheBreakState[].models[<model>].tool_count`**, with a `tools` list beside it.
- [x] T003 Enumerate the tool names for `--excluded-tools` from those recordings, and verify
      `tool_count: 0` on a real run. **Twenty names; nineteen recognised by 1.0.83.**
- [x] T004 **The enumeration was already incomplete, and C-1 caught it.** A run with two names
      dropped left `apply_patch` available to the model and **exited 0** with a well-formed
      answer. Kept verbatim as `tool-count-not-zero.jsonl` — it is the whole argument for making
      the closed shape a per-job assertion.
- [x] T005 **`--model` could not be pinned on this machine.** Every slug offered to `--model` was
      rejected with `Model "…" from --model flag is not available.`, including
      `mai-code-1.1-flash`, the model the CLI's own router had just chosen. Recorded in the spec's
      Assumptions; the pin is built and configurable, and C-5 is closed by measurement in §13
      step 12 on an account whose catalogue allows one.
- [x] T006 `tests/fixtures/copilot/` with `MANIFEST.json` naming, for every fixture, how it was
      produced, its exit code, its `tool_count`, and **whether it is verbatim** — one is derived
      (`malformed-final-answer.jsonl`) and says so.

## Phase 2: The executor

- [x] T007 `executor.py`: `_build_env(prefixes, extra_exact)` and the two allow-lists — Claude's
      `ANTHROPIC_*`/`CLAUDE_*`, Copilot's `COPILOT_*` + `GH_TOKEN`/`GITHUB_TOKEN`/`GH_HOST`,
      the common set shared, neither passing the other's, neither passing an interpreter variable
      (FR-011, C-4, R-3).
- [x] T008 `executor.py`: `COPILOT_EXCLUDED_TOOLS`, `COPILOT_MAX_PROMPT_BYTES`,
      `COPILOT_MIN_AI_CREDITS`, `COPILOT_AUTH_MARKERS` — each with its measurement in the comment
      beside it (FR-002, FR-004, FR-009).
- [x] T009 `executor.py`: `_render_copilot_prompt` — `SYSTEM` and `RESPONSE` above TASK and outside
      the fence, the shared `_render_prompt` body unchanged beneath them (FR-003, C-8).
- [x] T010 `executor.py`: the JSONL readers — `_copilot_session_errors`, `_copilot_tool_counts`,
      `_copilot_final_answer`, `_copilot_turn_count`, `_copilot_premium_requests`,
      `_copilot_exit_code`, `_strip_json_fence` (FR-005, FR-007).
- [x] T011 `executor.py`: `CopilotExecutor` — the argv, the 512 KB guard, the per-job `cwd`, the
      timeout that is ours because the CLI has none, `_assert_ran` then `_assert_closed_shape`
      then `_read_answer`, the one recovery pass, and `_envelope` with **no `total_cost_usd`**
      (FR-001..FR-010, C-1, C-2, C-3, C-7).
- [x] T012 `executor.py`: `_EXECUTORS` gains `claude` and `copilot`; `claude-code` resolved as a
      permanent alias by `config.canonical_executor_name`; `get_executor` gains `copilot_model`
      (FR-012, C-12).

## Phase 3: Which one runs

- [x] T013 `config.py`: `DEFAULT_EXECUTOR = "claude"`, `EXECUTOR_BINARIES`,
      `IN_PROCESS_EXECUTORS`, `EXECUTOR_ALIASES`, `canonical_executor_name`, `ENV_HOST_MARKERS`,
      `EXECUTOR_SOURCES`, `ENV_COPILOT_MODEL` (FR-012, FR-013).
- [x] T014 `config.py`: `host_from_environment` — one answer taken, **two answers meaning none**
      (FR-013 step 2, C-9).
- [x] T015 `config.py`: `resolve_executor` — the five steps, returning `(name, source)`; and
      `executor_on_path`, which never grows a `claude_on_path` (FR-013, FR-017, C-10).
- [x] T016 `config.py`: `resolve_copilot_model`; `RuntimeConfig.executor_source`/`copilot_model`
      and `StatusConfig.executor_source`; `load` and `load_status_config` both routed through the
      one resolver, so the startup line and `status` can never disagree (FR-015, FR-017).
- [x] T017 `cli.py`: `--host {claude,copilot,auto}` on `connect` only, `--copilot-model`, and
      `choices` on `--executor` (FR-014).
- [x] T018 `cli.py`: `executor_startup_lines` and the best-effort one-second `_binary_version`;
      printed immediately after `KEEL_ENVIRONMENT=`; the `ambiguous-path` comment; the
      `KEEL_EXECUTOR_UNAVAILABLE=` second line; `model=auto` said out loud (FR-016, C-5, C-9).
- [x] T019 `cli.py`: `_environment_keys` delegates both executor keys to the resolver (FR-017).

## Phase 4: The tests

- [x] T020 `tests/test_copilot_executor.py`: a fake `copilot` first on `PATH` replaying queued
      recordings; the completed run, the refused run, the malformed result, the auth failure, the
      timeout; the closed-shape check including the run that leaked `apply_patch`; the argv shape;
      the 512 KB guard; the fence; the recovery pass (FR-018).
- [x] T021 Same module: `BuildEnvAllowListTest` and `TheChildsEnvironmentTest` — both executors'
      allow-lists, and what a real child process actually received (C-4, R-3).
- [x] T022 Same module: `SubsetValidatorIsLoadBearingTest` — the whole path with `jsonschema`
      forced absent, including a result that violates `completed_result_schema` (R-2).
- [x] T023 `tests/test_executor_selection.py`: the selection order **as a table**, fifteen rows,
      with `PATH` faked so the table reads the same on the founder's Mac and on a bare runner
      (FR-013).
- [x] T024 Same module: the host markers on their own, including both hosts at once; the three
      startup-line shapes; `status` as a real subprocess under each input; the flags on `connect`
      and their absence from `status`/`disconnect` (FR-014, FR-016, FR-017).
- [x] T025 Two existing assertions updated, and only because this feature changed what they
      assert: `tests/test_config.py`'s default-executor test and `tests/test_cli_status.py`'s two
      exact-payload comparisons now read `claude`. Nothing else in the suite touched.
- [x] T026 `README.md`: both executors, the selection order, the new knobs, and Copilot's status in
      the design's own words — **"runs, unmeasured"**.

## Gate

- [x] G001 `python -m pytest` on **Python 3.9.19** (fresh venv, pytest only): **326 passed**.
- [x] G002 `python -m pytest` on **Python 3.13.13** (fresh venv, pytest only): **326 passed**.
      Neither venv has `keyring` or `jsonschema` — the shipped configuration (R-2).
- [x] G003 257 tests before, **326** after: +69.
- [x] G004 The three `KEEL_EXECUTOR=` shapes produced by a real `keel connect` on the founder's Mac
      (SC-005):
      ```
      KEEL_EXECUTOR=claude source=ambiguous-path binary=…/claude version=2.1.263 (Claude Code)  # both CLIs on PATH; pass --executor to choose
      KEEL_EXECUTOR=copilot source=flag binary=/opt/homebrew/bin/copilot version=GitHub Copilot CLI 1.0.83. model=auto
      KEEL_EXECUTOR=copilot source=host model=auto
      KEEL_EXECUTOR_UNAVAILABLE=copilot  # not on PATH; jobs report EXECUTOR_UNAVAILABLE
      ```

## Open, and deliberately not done here

- **C-5 is closed by mechanism, not by measurement.** No `--model` slug was accepted on the
  founder's Copilot account. §13 step 12 must run the instruction eval on an account whose
  catalogue allows a pin, and record the slug it used.
- **C-11 / A-11 — "supported" is a four-part gate and this is one part.** The runtime's suite
  passes; S-001 through Copilot, the instruction eval's run of record, and the release notes'
  version range are steps 10 and 12. Until then, **"runs, unmeasured"**, in those words.
- **The tool enumeration will rot again.** That is expected and it is why C-1 exists. When a job
  starts failing with `the closed shape was not held`, the fix is to read the recording's `tools`
  list and add the name — not to relax the check.
- **`tests/test_generate_bundled_script.py` needs `PyYAML`**, which the `dev` extra declares. It is
  pre-existing and unrelated; a 3.9 run without the extra skips nothing and errors on the import.
