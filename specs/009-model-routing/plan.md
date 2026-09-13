# Implementation Plan: The job names the model

**Branch**: `model-routing` | **Date**: 2026-09-13 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md) (FR-001..011, SC-001..004) and keel-cloud
`canon/designs/model-routing-design.md` §5, §6 (amended 2026-09-13), §10 step 2.

## Summary

Measure first, then move one value from the constructor to the call. The 0.4.0 executors already
knew how to pass a model to each CLI; what changes is *where the name comes from* — the job, and
nowhere else — and *what happens when the CLI says no* — one unpinned retry, reported. Every knob
that let this machine name a model goes, so the runtime has exactly one source of truth and the
skill and the page never carry a model name.

## Technical Context

- **The wire**: `request_payload.model` is a per-host map (`{"claude": ..., "copilot": ...,
  "codex": ...}`), optional and additive; `/complete` and `/fail` gain an optional `execution`
  object. No outcome-shape change (skill design decision 15).
- **The runtime stays stateless**: the model is read off the job in hand; nothing is remembered
  from the bind, nothing to refresh when the cloud's table changes.
- **Markers are measured**: three recordings, one per host, 2026-09-13, in `tests/fixtures/`.
  Copilot's is deliberately narrower than the §5.4 lookalike (the CAPIError names no flag).
- **Python 3.9 floor, stdlib only** under `keel_runtime/` (R-1, R-2); `str | None` only inside
  string annotations on the class attributes and the dataclass field.

## Design

1. `InferenceRequest.model`; `_first_string_for_keys`/`_find_string_key` for reading a reported
   model out of a stream.
2. Shared report helpers `_init_model_report`/`_begin_model_report`; per-host
   `*_MODEL_REFUSAL_MARKERS`, `_<host>_refused_model`, `_<host>_reported_model`.
3. Each executor: `host_key`, `host_version`, `_build_argv(..., model)`, `_invoke(..., model)`,
   and in `execute`: begin the report → first pass → refused-and-named? retry unpinned → the
   answering pass is the one asserted, read and (for Copilot/Claude) mined for the model name;
   the recovery pass (FR-011 of spec 002) keeps whatever model the answering pass used.
4. `poller`: `_model_for`, `_execution_report`, `execution.json`, `execution=` on complete/fail
   only when there is a report (so the older fakes and the scripted path see the same calls).
5. `cloud_client`: the two bodies take the optional object.
6. `config`/`cli`: remove the knobs; `probe_host_cli` shares one `--version` probe between the
   startup line and `executor.host_version`.
7. DRIFT #67: two sentences in `_COPILOT_RESPONSE_SECTION`.

## Risks

- A host CLI that changes its refusal sentence silently loses the retry (fails as today, no
  worse); the marker test ties each constant to its fixture so a re-measurement is one file.
- `model_used` after a Codex retry is unknown by construction; the cloud must treat `null` as
  "the default, unnamed", not as an error.
