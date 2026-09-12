# Tasks: The third host — `CodexExecutor`

**Input**: [spec.md](spec.md) (FR-001..011, SC-001..004), [plan.md](plan.md), keel-cloud
`canon/designs/keel-skill-design.md` decision 11.

**Rules**: standard library only under `keel_runtime/`; the scripted and stub executors untouched
(C-12); no wire change and no new outcome key (decision 15); `status` never exits non-zero.

**Gate**: `python -m pytest` green on Python 3.9 and the newest interpreter present, with
`jsonschema` absent.

## Phase 0 — measurement (done 2026-09-12, codex-cli 0.154.0)

- [X] T001 Install the CLI; sign in with the founder's plan (`codex login`, the founder's own act).
- [X] T002 Unauthenticated recording with an isolated `CODEX_HOME` → `unauthenticated-no-credential.{jsonl,stderr}`.
- [X] T003 A completed closed-shape job → `completed.jsonl`; the plain-mode header for the model name.
- [X] T004 The closed-shape pair, asked to run `ls -a` open and closed → `open-` / `closed-asked-to-run-a-command.jsonl`.
- [X] T005 `--output-schema` with Keel's envelope → `output-schema-refused-by-strict-mode.jsonl`.
- [X] T006 The injected order with the schema in the prompt → `needs-input.jsonl`.
- [X] T007 Host markers as a command Codex runs sees them; the skill under Codex, sandboxed and not.
- [X] T008 `MANIFEST.json` naming how every recording was produced.

## Phase 1 — the executor

- [X] T009 `CODEX_DISABLED_FEATURES`, `CODEX_EXEC_FLAGS`, `CODEX_MAX_PROMPT_BYTES`, `CODEX_AUTH_MARKERS`, `_CODEX_ENV_*` in `executor.py`.
- [X] T010 `_codex_error_messages`, `_codex_items`, `_codex_tool_items`, `_codex_final_answer`, `_codex_turn_count`, `_codex_usage`, `_mentions_codex_auth_failure`.
- [X] T011 `CodexExecutor` (FR-001..008), `_make_codex`, `_EXECUTORS["codex"]`, `get_executor(codex_model=)`.

## Phase 2 — selection and the CLI

- [X] T012 `config.py`: `EXECUTOR_BINARIES`, `ENV_HOST_MARKERS`, `host_from_environment`, `resolve_executor` step 3 for three CLIs, `ENV_CODEX_MODEL`, `resolve_codex_model`, `Config.codex_model`.
- [X] T013 `cli.py`: `--executor codex`, `--host codex`, `--codex-model`, `model=default`, the ambiguous-path wording for more than two CLIs.

## Phase 3 — tests and words

- [X] T014 `tests/test_codex_executor.py` (18 tests) and the selection table's five new rows, the `model=default` line test.
- [X] T015 `README.md`: three hosts in "Which executor runs"; the `codex` bullet under "Executors".
- [X] T016 The suite green on 3.9 and 3.13 (434 passed each).

## Sibling repositories (their own commits)

- [X] T017 keel-connect-skill: `HOST_CODEX`, `detect_host`, `HOST_EXECUTORS`, `--host codex`; tests (126 green).
- [X] T018 keel-connect-skill packaging: `marketplace.codex.json.in` → `dist/marketplace/.agents/plugins/marketplace.json`; test; READMEs.
- [X] T019 keel-e2e-eval: `instructions.run --host codex`, `_codex_ready`, the Copilot-shaped prompt for codex, report names, the harness scrub list.
- [ ] T020 keel-cloud canon: §5.3's table and decision 11's list say Codex is in.
- [ ] T021 The gate (decision 10): `make instruction-eval HOST=codex` in full — the founder's word.
- [ ] T022 The skill's reply on a sandboxed host (spec.md Assumptions): measure interactive Codex, then decide in keel-connect-skill.
