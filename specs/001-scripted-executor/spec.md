# Feature Specification: The scripted executor (a deterministic runtime for end-to-end runs)

**Feature Branch**: `001-scripted-executor`

**Created**: 2026-09-03

**Status**: Draft — for the founder's review

**Input**: keel-e2e-eval's rewrite for the connect stack (`keel-e2e-eval/specs/005-connect-stack/`)
needs a runtime that answers every inference screen with a valid, screen-shaped result, without
an LLM, so one founder journey can be driven end to end deterministically. Today's `--executor
stub` (spec 020 FR-028) echoes; it can prove the queue but cannot frame a problem.

## Scope

One new executor, `scripted`, selected with `--executor scripted`, never a default. It reads a
**script**: a JSON file of results keyed by screen, consumed in order per screen, and answers each
job from it. Nothing else in the runtime changes: the same poll loop, the same
`response_validator`, the same `complete`/`fail` calls. The stub executor stays as it is.

**Not in scope**: any change to Keel Cloud. The request payload carries no `screen` field; the
executor infers the screen from the payload's own `context` keys, which spec 022 (keel-cloud)
fixes per screen (its FR-010 table).

## User Scenarios & Testing

### User Story 1 - A referee drives a whole discovery through a real runtime without an LLM (Priority: P1)

keel-e2e-eval boots Postgres, keel-cloud, keel-web and this runtime with `--executor scripted
--script <payroll-exceptions.json>`; a browser types the problem; the runtime answers with the
script's problem statement; the founder confirms; the runtime answers with the script's beliefs
and roles; and so on through the solution, the price, the readings of three participants'
answers. Every result validates against the screen's `response_contract`, so Cloud applies it,
and the browser sees exactly the payroll-exceptions project the mockups of record draw.

**Independent Test**: with the bundled script, feed the executor a synthetic `InferenceRequest`
for each of the ten screens' context shapes → each returns `{outcome: COMPLETED, result: …}` (or
the scripted `NEEDS_INPUT` where the script says so) that passes `response_validator` against the
screen's `completed_result_schema` as spec 022 FR-012 defines it → a second request for the same
screen returns the script's second entry, or the last entry again when the list is exhausted.

**Acceptance Scenarios**:

1. **Given** a payload whose `context` keys are exactly `{project_name}`, **When** executed,
   **Then** the screen is `PROBLEM_FRAME` and the result is the script's first `PROBLEM_FRAME`
   entry.
2. **Given** a script entry `{"outcome": "NEEDS_INPUT", "questions": [...]}` for a screen,
   **When** it is the next entry, **Then** the executor returns it verbatim; the following
   request for the same screen (turn 2, with `interaction_history` non-empty) returns the next
   entry.
3. **Given** a screen with no entries in the script, **When** executed, **Then**
   `ExecutorUnavailable("scripted executor has no entry for <screen>")` — the runtime fails the
   job honestly rather than inventing.
4. **Given** the bundled default script, **When** every screen is exercised once, **Then** every
   result validates against the corresponding contract (asserted by a test that carries the
   ten contracts' schemas, copied from spec 022 FR-012).

### Edge Cases

- Screen inference by context keys (from keel-cloud spec 022 FR-010; the executor must implement
  exactly this table and nothing looser):
  `{project_name}` → PROBLEM_FRAME; `{problem_statement, existing_roles}` → PROBLEM_ASSUMPTIONS;
  `{project_name, problem_statement, existing_roles}` → SOLUTION_FRAME;
  `{solution_statement, problem_statement, existing_roles}` → SOLUTION_ASSUMPTIONS;
  `{project_name, problem_statement, solution_statement, existing_roles}` → COMMERCIAL_FRAME;
  `{commercial_statement, problem_statement, solution_statement, existing_roles}` →
  COMMERCIAL_ASSUMPTIONS; `current_statement` present with `solution_statement` absent →
  SOLUTION_REFRAME, present → COMMERCIAL_REFRAME; `invitation_id` present → INTERPRET;
  `deal_breakers` present → BRIEF. Unknown key set → `ExecutorUnavailable` naming the keys.
- **INTERPRET results must echo `invitation_id`** from the context into `invitationId` (Cloud
  refuses otherwise, spec 022 FR-016). The script's INTERPRET entries therefore carry `perAnswer`
  only; the executor fills `invitationId` from the context. Likewise `perAnswer[].assumptionId`
  must name real ids: the script's INTERPRET entries key evidence by **assumption heading**, and
  the executor resolves headings to ids through the context's `assumptions[]` (`{id, heading,
  statement}`); an unresolvable heading → `ExecutorUnavailable`.
- **Role reuse by label** in `*_ASSUMPTIONS` entries follows spec 022's own rule: the script
  writes `{role: {new: {...}}}` the first time a label appears and `{role: {reuse: <label>}}`
  after; the executor does not rewrite roles — it is the script author's job, and the bundled
  script does it correctly.
- Script consumption is per screen, in order, **per executor process**; a restarted runtime
  starts the script over. keel-e2e-eval boots one runtime per run.
- `--script` absent with `--executor scripted` → the bundled default,
  `keel_runtime/testing/scripts/payroll-exceptions.json`.

## Requirements

- **FR-001** `keel_runtime/testing/scripted_executor.py`: `ScriptedExecutor(script: dict)`
  implementing `Executor.execute`; screen inference per the edge-case table; per-screen cursors;
  the INTERPRET id resolution above.
- **FR-002** `get_executor("scripted")` loads it lazily like `stub`; `connect` gains
  `--script PATH` (only meaningful with `--executor scripted`; ignored otherwise with a logged
  warning). `KEEL_SCRIPT` env as the fallback, flag wins — the same precedence the other flags
  use.
- **FR-003** The bundled script `keel_runtime/testing/scripts/payroll-exceptions.json`: the
  payroll-exceptions journey exactly as keel-cloud `canon/mockups/` draws it — the problem
  statement ("Payroll managers at 200–800-person companies lose a day of two people's time every
  month reconciling payroll exceptions that nobody owns until payday forces the question."), its
  beliefs and roles (a payroll manager; someone who runs a payroll team), the solution statement
  ("An exceptions queue inside the payroll tool that assigns every exception an owner the day it
  appears."), its beliefs, the commercial statement ("$30 a seat per month, billed annually
  upfront.") with its beliefs and the buyer role ("someone who signs off on payroll software
  spend"), and INTERPRET entries for three participants (Dana Okafor, Wei Zhang, Marcus Webb)
  whose evidence produces: problem *People disagree* (the "hours, not minutes" belief split 2–1),
  solution *Holding up*, commercial *Not holding up* (three against "annually, upfront"). Each
  `PROBLEM_FRAME` list carries **one `NEEDS_INPUT` entry first** ("When you say chasing exceptions
  — is the cost the hours, or is it that mistakes get through to payday?") and then the
  statement, so the smoke exercises a follow-up turn. No BRIEF entry is needed (the MVP brief is
  derived); include one anyway so the screen stays exercisable.
- **FR-004** Tests (`tests/test_scripted_executor.py`): the four acceptance scenarios; the
  screen-inference table exhaustively; the id resolution; exhaustion and missing-screen
  refusals; and a contract-validity test over the bundled script using the ten
  `completed_result_schema`s copied verbatim from keel-cloud spec 022 FR-012 into
  `tests/fixtures/response_contracts.json` (with a comment naming the source; when Cloud's
  contracts change, this file is re-copied — it is a pin, not a second source of truth).
- **FR-005** `README.md`: a "Running deterministically" section; `--help` text for the flag.
- **FR-006** Stdlib only (pyproject's rule); `jsonschema` used only when importable, as
  `response_validator` already does.

## Success Criteria

- **SC-001** `python3 -m pytest tests -q` green, including the new file.
- **SC-002** keel-e2e-eval's smoke (its spec 005) completes a whole discovery against this
  executor with zero `INVALID_LLM_RESPONSE` or `RESULT_INVALID` outcomes.

## Assumptions

- The runtime is launched uninstalled (`python3 -m keel_runtime connect …`) by keel-e2e-eval,
  exactly as keel-cloud's own journey test launches it.
- keel-cloud may later add `screen` to the request payload; if it does, the executor prefers it
  over inference, and the inference table stays as the fallback.
