# Amendment: the scripted executor follows the measured-beliefs contracts

**Amends**: [`spec.md`](spec.md) (the scripted executor, 2026-09-03) — its FR-002, FR-003,
FR-004, its acceptance scenarios and its edge cases.

**Branch**: `scripted-executor-measured` | **Date**: 2026-09-07

**Input**: keel-e2e-eval spec `010-measured-beliefs-eval`, §*Requirements on keel-runtime*,
RT-001–RT-006. That repo is the referee of this one and does not edit it; it states the
requirement and the change is made here.

*Spec kit is not used in this repository. This file is the record — there is no plan.md and no
tasks.md, and the work is one branch and one review.*

---

## What was wrong

The original spec said the screen is inferred from the request payload's own `context` keys,
"which spec 022 (keel-cloud) fixes per screen (its FR-010 table)", and the executor implemented
that table **by hand**. Fifteen weeks later every row of it was stale:

| Row | What it said | What keel-cloud writes now |
|---|---|---|
| `PROBLEM_FRAME` | `{project_name}` | `{project_name, market}` |
| `PROBLEM_ASSUMPTIONS` | `{problem_statement, existing_roles}` | `+ market, founder_name` |
| `SOLUTION_FRAME` | `{project_name, problem_statement, existing_roles}` | `+ market` |
| `SOLUTION_ASSUMPTIONS` | `{solution_statement, problem_statement, existing_roles}` | `+ market, founder_name` |
| `COMMERCIAL_FRAME` | `{project_name, problem_statement, solution_statement, existing_roles}` | `+ market` |
| `COMMERCIAL_ASSUMPTIONS` | the four above minus `project_name` | `+ market, founder_name` |
| `SOLUTION_REFRAME` / `COMMERCIAL_REFRAME` | `current_statement` present | fixed sets, both ending `market` |
| `INTERPRET` | `invitation_id` present | `{invitation_id, anchors}` — `assumptions` is gone |
| `BRIEF` | `deal_breakers` present | `{project_name, market, claims}` — `deal_breakers` is gone |
| — | — | **three new** `<SCREEN>.correction` key sets, carrying `current_draft` and `founder_message` |

Because the table matched key sets exactly — deliberately, and still — **every job missed**. A
run died at the first inference job with `ExecutorUnavailable`. The result shapes had moved too:
`claimType`, `stance`, `perAnswer`, `assumptionId` and `evidence` no longer exist anywhere, and
the bundled `payroll-exceptions.json` was written entirely in them, so `--executor scripted` with
no `--script` was a trap that failed with a schema error rather than a clear one.

The root cause is not that keel-cloud moved. It is that **a hand-copied table is a claim about
another repository that nothing checks.**

## What changed

**A1 (RT-001) — the table is loaded, not written.** `keel_runtime/testing/scripted_executor.py`
now reads keel-cloud's own `context-keys.json` — the file its
`./gradlew -q screenContracts --args="export <dir>"` writes — into `{frozenset(keys): screen}`,
resolved by `--context-keys` > `KEEL_CONTEXT_KEYS` > `$KEEL_HOME/config.json` > the bundled copy
at `keel_runtime/testing/contracts/context-keys.json`. There is no transcription left to rot.

Two properties make exact matching right rather than fragile, and both are keel-cloud's, not
ours: it writes **every** key for a screen, filling an absent value with `null` rather than
omitting it; and no two screens share a key set. The loader asserts the second and refuses a
table that breaks it, because inference by exact match is only honest while it holds.

The three special cases the old code needed (`current_statement` present → a reframe,
`invitation_id` present → `INTERPRET`, `deal_breakers` present → `BRIEF`) are **gone**. Every key
set is now fixed and complete, so a single exact match is the whole rule.

**Strictness is kept** (keel-e2e-eval spec 010 judgement call 6). An unknown key set raises
`ExecutorUnavailable` naming the keys — including a *superset* of a known one, which is the shape
the next keel-cloud key addition will take. The cost of strictness is exactly this amendment,
every time keel-cloud adds a context key. It is paid on purpose: a loose executor would have
answered the wrong screen silently and this drift would never have surfaced at all.

**A2 (RT-002) — `_resolve_interpret_result` is rewritten.** The heading-to-id resolution went
away with the `assumptions[]` it resolved through. An `INTERPRET` context is
`{invitation_id, anchors[]}` where an anchor is `{anchor_id, prompt, text, tap}`. The executor
still fills `invitationId` from the context (keel-cloud refuses otherwise) and now passes each
`anchorings[].anchorId` through **unchanged**, refusing an id the context's `anchors[]` does not
carry — the same honesty the heading rule had. A blank answer is never written into the context,
so a script that answers one is answering something the reader was never shown, and that is now
a refusal rather than a silent pass.

**A3 (RT-003) — the shapes.** The script may carry
`{assumptions, questionnaire: {introduction, anchors}, normalization_rationale}` for the three
assumption screens and `{invitationId, anchorings, unprompted, flags}` for the reading.
`tests/fixtures/response_contracts.json` was **regenerated from the exporter** rather than
hand-corrected, and now carries all thirteen contracts including the three corrections. A test
asserts no retired key appears in it, or in the bundled script, ever again.

**A4 (RT-004) — the bundled script is retired and replaced.** `payroll-exceptions.json` is
**deleted**: its shapes cannot be expressed in the current contracts, so there was nothing to
regenerate. The new default is `keel_runtime/testing/scripts/countly-problem.json` — the
`PROBLEM` stage of keel-cloud's frozen golden corpus entry `01-countly`: one framing statement,
eight beliefs with their expectations and one role, one anchor with its seven selections, and
eleven readings, one per person who wrote under that anchor.

It is **generated, never hand-written** — `tools/generate_bundled_script.py`, a developer tool
outside the package (it imports `yaml`; the runtime itself stays standard-library-only). The
generator refuses rather than invents: a belief naming a selection its own stage's questionnaire
does not offer, a belief asked of an unknown role, a tap outside the table, or a written anchor
the corpus records no anchoring for. It makes exactly one transformation to a corpus value —
dropping the keys the corpus writes as `null` inside an `expectation` (`lower: null`,
`measure.per: null`), which the wire types as an object and a string. An absent bound and a null
bound are the same claim, so this changes no meaning; it is recorded here because it is the only
place the generator is not a straight copy.

The corpus has no `askedOf` on the wire: a belief's corpus `askedOf` is a **role id**, and the
generator resolves it to `role.new` for the first belief that names a role and `role.reuse` for
every later one.

**A5 (RT-005) — `KEEL_SCRIPT`.** Already met before this branch: `keel_runtime/config.py`'s
`ENV_SCRIPT` has resolved it under the standard flag > env > config-file precedence since the
scripted executor shipped, and the README already documented it. Verified and left alone. What is
new beside it is `KEEL_CONTEXT_KEYS`, on exactly the same shape, so an operator who hands this
runtime a script can hand it that script's contemporaneous table too.

**A6 (RT-006) — the tests are restated in the repo that owns the table.**
`tests/test_scripted_executor.py` no longer transcribes the table either: every inference test is
**driven from the same `context-keys.json` the executor loads**, so it asserts that the executor
implements keel-cloud's export rather than that it agrees with a second hand-written copy. Added
beside that: a regression test that each of the five retired key sets now *misses*; a superset
test; an operator-supplied-table test; the `anchorId` passthrough and its refusal; and the bundled
script validated against every one of its screens' exported contracts.
`tests/test_poller.py` gains one pass of a **real** `ScriptedExecutor` through `_handle_job`, so
the poller and the rebuilt executor are proved to still fit together — including that an
un-inferrable context fails the job with `LLM_UNAVAILABLE` naming the offending key.

## Provenance

The bundled `context-keys.json`, the regenerated `tests/fixtures/response_contracts.json` and the
bundled `countly-problem.json` were all produced from **keel-cloud commit `89a2315`** (branch
`028-measured-beliefs-aggregate`, 2026-09-07, *"Spec 030: the tests, and the record"*), by running
its own `screenContracts` task against a clean checkout of that commit. keel-cloud was read and
never written.

This branch was first built against `03ebe60` and regenerated at the end against `89a2315`, which
landed while it was in flight. The two exports are **semantically identical** — same thirteen key
sets, same thirteen contracts — and differ only in the order the exporter happens to write keys
within a JSON object, which is not stable between runs. A future regeneration will therefore show
a large textual diff and no change at all; compare with sorted keys before believing one.

Regenerating, when keel-cloud next moves:

```sh
./gradlew -q screenContracts --args="export /tmp/keel-contracts"     # in keel-cloud
cp /tmp/keel-contracts/context-keys.json  keel_runtime/testing/contracts/
python3 tools/generate_bundled_script.py \
    --corpus ../keel-cloud/canon/designs/measured-beliefs/corpus/01-countly.yaml \
    --stage PROBLEM --out keel_runtime/testing/scripts/countly-problem.json \
    --keel-cloud-commit <the commit>
python3 -m pytest
```

If the tests go red after that, keel-cloud changed a contract — which is the whole point of them.

## What is *not* changed

- The poll loop, `response_validator`, `complete`/`fail`, the stub executor, the claude-code
  executor, and every other flag.
- The strictness of `infer_screen`. It was offered a looser rule and it is keeping the strict one.
- The 300-second job wall clock (`timeout-configurable`, this branch's parent). Named in
  keel-e2e-eval's spec only as a dependency of its live run, not as this feature's to specify.

## Amended requirements, for the record

| Original | Now reads |
|---|---|
| **FR-002** `--script`, flag > env > config, bundled default | unchanged, but the bundled default is `countly-problem.json`; `--context-keys` / `KEEL_CONTEXT_KEYS` / `context_keys` joins it on the same precedence |
| **FR-003** the screen is inferred from spec 022 FR-010's table | the screen is inferred from keel-cloud's exported `context-keys.json`, by exact key-set match, from a path the runtime is given, with a bundled copy as fallback |
| **FR-004** the bundled script validates against every screen's contract | unchanged, against the **regenerated** contracts; the bundled script now covers one stage (`PROBLEM_FRAME`, `PROBLEM_ASSUMPTIONS`, `INTERPRET`) rather than all ten screens, and says so |
| **§Edge Cases** heading → `assumptionId` resolution | `anchorId` passthrough, refusing an id the context's `anchors[]` does not carry |
