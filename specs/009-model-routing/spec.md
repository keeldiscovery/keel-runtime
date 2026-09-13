# Feature Specification: The job names the model — model routing in the runtime

**Feature Branch**: `009-model-routing` (branch `model-routing`)

**Created**: 2026-09-13

**Status**: Implemented (runtime half); the cloud half is keel-cloud's own spec

**Input**: the founder, 2026-09-12/13 — *"we need to pin to a model … we don't need the most
advanced model"*; *"after the connect, when the instruction comes from the runtime, the
instruction should tell which model to pin to"*; *"a table by Codex, Copilot or Claude"*; and,
on the 0.4.0 pins, *"that's not a concept"* — against keel-cloud
`canon/designs/model-routing-design.md` §5 (the wire), §6 (the runtime, as amended 2026-09-13:
one rule, no founder's pin) and §10 step 2.

## Scope

`keel_runtime/executor.py`, `keel_runtime/poller.py`, `keel_runtime/cloud_client.py`,
`keel_runtime/config.py`, `keel_runtime/cli.py`, `README.md`, one new test module, three new
fixture recordings (one per host) and a new `tests/fixtures/claude/` directory. **Out of scope**:
the routing table itself and the `model` key's production (keel-cloud), the eval's `--models`
file (keel-e2e-eval), the skill's bundled runtime refresh (keel-connect-skill, `make runtime`).

Also carried on this branch, separately reported: the keel-e2e-eval **DRIFT #67** prompt fix —
two sentences in the Copilot-shaped prompt's RESPONSE section (Codex reads it too) naming the
forbidden word *proxy* and the allowed units. A prompt change, never a mark change.

## What was measured before anything was written (2026-09-13, the founder's Mac)

Each host's own words for a model it will not serve, recorded verbatim in
`tests/fixtures/<host>/` with a `MANIFEST.json` row (`claude/` is new):

1. **Codex 0.154.0, ChatGPT plan, `-m gpt-5.5-mini`**: exit 1; `thread.started`, `turn.started`,
   one `error` and one `turn.failed`, both carrying the API's 400 — *"The 'gpt-5.5-mini' model
   is not supported when using Codex with a ChatGPT account."* — nothing on stderr but the stdin
   notice. `-m not-a-model` is refused with the same sentence after an `item.completed` error
   item *"Model metadata for `not-a-model` not found"*. On an **API-key** sign-in the refusal is
   the API's 404, *"The model `gpt-5.5-mini` does not exist or you do not have access to it."*,
   repeated through the reconnects and the HTTPS fallback (`unsupported-model-on-api-key.jsonl`).
2. **Copilot CLI 1.0.83, `--model not-a-model`**: exit 1, **no JSONL**, one stderr line —
   *`Error: Model "not-a-model" from --model flag is not available.`* Distinct from the CAPIError
   400 *"The requested model is not supported"* an invalid token once produced inside a
   `session.error` (design §5.4), which names no flag.
3. **Claude Code 2.1.270, `--model not-a-model`**: exit 1; the `init` event echoes the flag as its
   `model`; one `assistant` message with `model: "<synthetic>"`; the `result` is `is_error: true`,
   `subtype: success`, `terminal_reason: api_error`, `total_cost_usd: 0`, text *"There's an issue
   with the selected model (not-a-model). It may not exist or you may not have access to it."*;
   stderr `[claude-code:unrecognized_model] {...}`.
4. **What each stream says about the model that ran**: Claude Code's `init` event names it (an
   alias resolves to the full name there); Copilot's stream carries `chosenModel` (and `model`
   keys); Codex's JSONL names no model at all (`codex/MANIFEST.json`, `completed.jsonl`).

## User Stories

**US1 — the cloud's model reaches the CLI.** A job whose `request_payload.model` names this host
runs on that model; a job that does not runs on the CLI's default. The same runtime, the same
executor, two consecutive jobs, two different flags.

**US2 — a refused model does not fail the founder's screen.** When the CLI refuses the named
model in its measured words, the job runs once more with no model flag and completes; the
completion says both what was asked and what ran.

**US3 — the cloud learns which host answered.** Every completion and failure from a host
executor carries `execution` — host, CLI version, model requested, model used, whether it was
retried — so the morning status can say *"Codex refused the light pin on 4 jobs yesterday"* and
the table's owner can act.

**US4 — nothing on the machine names a model.** No flag, no variable, no config key. The knobs
0.4.0 shipped are gone, and setting them does nothing.

## Functional Requirements

- **FR-001** `InferenceRequest.model: str | None`, set by `poller._model_for` from
  `request_payload["model"][<executor.host_key>]` when that is a non-empty string; `None` for a
  missing key, a missing host entry, a non-map, a non-string or an empty string.
- **FR-002** Each host executor declares `host_key` (`"claude"`, `"copilot"`, `"codex"`); the
  scripted and stub executors declare none and are never pinned (C-12, untouched).
- **FR-003** The model is passed **per call**, only when present: `claude --model X`,
  `copilot --model X`, `codex -m X`. The constructors take no model; `get_executor` takes no
  `*_model` argument.
- **FR-004** `config.py` has no `ENV_*_MODEL`, no `resolve_*_model`, and `RuntimeConfig` no
  `*_model` field; `cli.py` has no `--claude-model`/`--copilot-model`/`--codex-model`; the
  `KEEL_EXECUTOR=` startup line carries no `model=` word.
- **FR-005** Each host executor exposes, reset per job: `last_model_requested`, `last_model_used`,
  `last_retried_unpinned`, plus `host_version` (set once by `cli._run_connect` from the same
  `--version` probe the startup line prints; `None` when unset).
- **FR-006** When a model was named and the first pass matches that host's **measured** refusal
  marker (`CLAUDE_MODEL_REFUSAL_MARKERS`, `COPILOT_MODEL_REFUSAL_MARKERS`,
  `CODEX_MODEL_REFUSAL_MARKERS`), the job is invoked once more with no model flag, in the same
  job directory; `last_retried_unpinned` is `True`; the refused pass's events stay in the log
  ahead of the answering pass's; the closed-shape and ran checks read the answering pass. No
  model named, or any other failure: no retry, the failure is what it was.
- **FR-007** `last_model_used` is the model the CLI reported for the answering pass (Claude's
  `init` event, never the refused pass's echo or `<synthetic>`; Copilot's `chosenModel`, then
  `resolvedModel`, then `model`), else the requested model when not retried, else `None`.
- **FR-008** `/complete` and `/fail` bodies gain an optional `execution` object —
  `{host, host_version, model_requested, model_used, retried_unpinned}` — present only for an
  executor with a `host_key`; an executor without one produces the 0.4.0 bodies byte for byte.
- **FR-009** `$KEEL_HOME/jobs/<id>/execution.json` holds the same object, beside `envelope.json`.
- **FR-010** The Copilot-shaped RESPONSE section names the allowed units for a measure and the
  forbidden word *proxy*; the Claude-shaped prompt is unchanged (DRIFT #67).
- **FR-011** Version 0.5.0.

## Success Criteria

- **SC-001** `python -m pytest` green on 3.9 and 3.13 with `jsonschema` absent.
- **SC-002** Every refusal marker is a substring of its own fixture (a test asserts it).
- **SC-003** The three retry tests replay the measured refusal then a measured completion and
  see exactly two invocations, the second without a model flag.
- **SC-004** The selection table, the startup line and the parser reject/omit every removed knob.

## Assumptions

- The Codex API-key sign-in's own wording is measured too (2026-09-13, `-m gpt-5.5-mini` on an
  API-key home: the API's 404 *"The model `gpt-5.5-mini` does not exist or you do not have
  access to it."*, `codex/unsupported-model-on-api-key.jsonl`), so both sign-ins retry. Models
  that key serves, for the table's owner: gpt-6-astra, gpt-5.6-terra, gpt-5.6-luna, gpt-5.6-sol,
  gpt-5.5, gpt-5.4-mini, gpt-5-mini, gpt-5-nano.
- A retry costs one more CLI call; the cloud's table is expected to name models a host can serve
  (design §7's process rule), so retries are a signal for the table's owner, not a steady state.
