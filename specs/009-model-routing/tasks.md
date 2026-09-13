# Tasks: The job names the model

**Input**: [spec.md](spec.md) (FR-001..011, SC-001..004), [plan.md](plan.md), keel-cloud
`canon/designs/model-routing-design.md` §5/§6/§10.

**Rules**: standard library only under `keel_runtime/`; the scripted and stub executors untouched
(C-12); no outcome-shape change (decision 15); a marker nobody recorded is not a marker.

**Gate**: `python -m pytest` green on Python 3.9 and the newest interpreter present, with
`jsonschema` absent.

## Phase 0 — measurement (done 2026-09-13)

- [X] T001 Codex 0.154.0 on the plan, `-m gpt-5.5-mini` and `-m not-a-model` with an isolated
      `CODEX_HOME` → `codex/unsupported-model-on-plan.{jsonl,stderr}`, `codex/unknown-model.jsonl`.
- [X] T001b Codex 0.154.0 on an API-key home, `-m gpt-5.5-mini` → `codex/unsupported-model-on-api-key.{jsonl,stderr}`
      (cf-ray and request ids scrubbed); second marker added.
- [X] T002 Copilot 1.0.83, the closed argv with `--model not-a-model` → `copilot/unknown-model.stderr`.
- [X] T003 Claude Code 2.1.270, the closed argv with `--model not-a-model` →
      `claude/unknown-model.{jsonl,stderr}` (init event scrubbed of the machine's inventory) and
      a new `claude/MANIFEST.json`.
- [X] T004 `MANIFEST.json` rows for all three, saying how each was produced and what it shows.

## Phase 1 — the executors

- [X] T005 `InferenceRequest.model`; the two stream-reading helpers; the report helpers.
- [X] T006 Claude: `host_key`, per-call `--model`, `CLAUDE_MODEL_REFUSAL_MARKERS`, retry, the
      `init`-event model read off the answering pass only.
- [X] T007 Copilot: the same with `--model`, `COPILOT_MODEL_REFUSAL_MARKERS` (stderr, before
      `_assert_ran`), `chosenModel`/`resolvedModel`/`model`.
- [X] T008 Codex: the same with `-m`, `CODEX_MODEL_REFUSAL_MARKERS` (the error stream, before
      `_assert_ran`), `model_used` = requested or None.
- [X] T009 Factories and `get_executor` without the three model arguments.
- [X] T010 DRIFT #67: the two RESPONSE sentences (FR-010).

## Phase 2 — the poller, the client, the CLI, the config

- [X] T011 `poller._model_for`, `_execution_report`, `execution.json`, `execution=` on
      `/complete` and `/fail` only when there is a report.
- [X] T012 `cloud_client.complete_job`/`fail_job` take the optional object.
- [X] T013 `config.py`: the three `ENV_*_MODEL`/`DEFAULT_*_MODEL` pairs, the three resolvers and
      the three `RuntimeConfig` fields removed.
- [X] T014 `cli.py`: the three flags removed; `probe_host_cli`; the startup line without
      `model=`; `executor.host_version` set from the one probe.

## Phase 3 — tests and words

- [X] T015 `tests/test_model_routing.py` (23 tests): `_model_for`, the reports on complete and
      fail, the client bodies, three retry suites, the marker-in-fixture check, the two prompt
      sentences (and the Claude prompt unchanged).
- [X] T016 The 0.4.0 tests moved to the per-call shape; the removed knobs asserted absent
      (`NoModelKnobTest`, `test_connect_has_no_model_flag_for_any_host`,
      `test_the_line_carries_no_model_word_for_any_host`).
- [X] T017 `README.md`: "Which model runs"; the flag and precedence tables; the argv blocks; the
      startup-line examples.
- [X] T018 Version 0.5.0.
- [X] T019 The suite green on 3.9 and 3.13 with `jsonschema` absent (SC-001): 463 passed, 1 skipped, each.

## Sibling repositories (their own commits, not this branch)

- [ ] T020 keel-cloud: the table, `InferenceScreen.jobClass()`, the `model` key,
      `execution` stored and logged (design §10 step 1).
- [ ] T021 keel-e2e-eval: `--models <file>` written into each case's job `model` map, replacing
      the `KEEL_<HOST>_MODEL` environment the runner sets today (design §10 step 3).
- [ ] T022 keel-connect-skill: `make runtime` to bundle 0.5.0; the skill's own wording unchanged.
