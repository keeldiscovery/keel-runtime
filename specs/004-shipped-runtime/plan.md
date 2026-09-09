# Implementation Plan: The runtime that ships inside the skill

**Branch**: `004-shipped-runtime` | **Date**: 2026-09-08 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md) (FR-001..011, SC-001..005) and the design of record, keel-cloud
`canon/designs/keel-skill-design.md` §3, §4, §6, §7, §9, §12, §13 step 1, §14.

## Summary

Four small, independent changes to one package, and one new workflow. The floor moves to Python
3.9 and a matrix holds it there without installing the optional accelerators; the runtime learns to
say which runtime it is; the credential home stops being one directory for every Keel and becomes
one directory *per* Keel, derived from the resolved base URL; and `status`/`connect` start naming
the environment they are pointed at, because the skill that carries them is forbidden to know any
address itself. Nothing else in the runtime moves: the poller, both test executors, the wire shapes
and the zero-dependency posture are untouched.

## Technical Context

**Language/Version**: Python **3.9** (floor) through 3.13. `from __future__ import annotations` is
already in every annotating module, so PEP 604 annotations stay legal at 3.9.

**Primary Dependencies**: none, and that is the point (R-1). `keyring` and `jsonschema` remain
optional and `try: import`-guarded (R-2). `PyYAML` is a test-only dependency of
`tools/generate_bundled_script.py`, declared as a `dev` extra.

**Storage**: the filesystem under `$KEEL_HOME` — `credentials.json` (`0600`), `config.json`,
`runtime.heartbeat.json`, `jobs/<job_id>/`. This feature changes **where that directory is**, never
what is in it.

**Testing**: `unittest` modules under `tests/`, run with `python -m pytest` or
`python3 -m unittest discover -s tests -t .`. 181 tests before this feature.

**Target Platform**: macOS, Linux and Windows; the founder's `/usr/bin/python3` 3.9.6 is the floor
bed, `debian:11-slim` the other (§10.4, §10.3).

**Project Type**: single Python package with a CLI (`keel`, `python3 -m keel_runtime`).

**Constraints**: standard library only in `keel_runtime/`; `status` never exits non-zero and never
makes a network call (R-4); one line of JSON on `status`'s stdout, always; no wire change.

**Scale/Scope**: ~2,100 lines of runtime source; this feature touches four files of it.

## Constitution Check

This repository has no constitution file. The rules it is held to are the design's invariants, and
each is cited by id in the code comment, the spec requirement and the test that checks it:

| Invariant | How this plan satisfies it |
|---|---|
| **R-1** runs on 3.9 with nothing installed | `requires-python = ">=3.9"`; the 3.9 row of the matrix; the import-blocked subprocess test |
| **R-2** `keyring`/`jsonschema` stay optional | the matrix installs neither and asserts both unimportable; the stdlib validator is driven directly by tests |
| **R-4** `status` never fails, never calls the network | `load_status_config` keeps its own resolution and never raises `SystemExit`; the no-base-URL test |
| **E-1** two Keels never share a credential | the derived home, and the two-base-URLs-one-`$HOME` test |
| **E-2** `CLOUD_BASE_URL` is the last term | the chain's order, and tests with the constant set and empty |
| **C-10** `executor`/`executor_on_path` in both shapes | one `_status_environment_keys()` helper used by both branches; `claude_on_path` is never built |
| **D5** no host name in a founder-facing reply | `environment` is an address; the only CLI names in the runtime are executor names, which are the runtime's own vocabulary |

## Project Structure

### Documentation (this feature)

```text
specs/004-shipped-runtime/
├── spec.md              # what lands and why
├── plan.md              # this file
└── tasks.md             # the ordered list, ticked as it went, with Discovered
```

No `research.md`, `data-model.md` or `contracts/` here: the research is the design of record and is
cited section by section, the only entity is a directory name, and the one contract this touches
lives in another repository (keel-cloud `specs/021-keel-runtime-status/contracts/`, amended by
§13 step 2, which is not ours).

### Source Code (repository root)

```text
keel_runtime/
├── __init__.py            __version__, __license__            (FR-004)
├── cli.py                 --version/--license, status keys,
│                          connect's KEEL_ENVIRONMENT line     (FR-005, FR-009, FR-010)
├── config.py              CLOUD_BASE_URL, host_slug,
│                          derive_home, environment_for,
│                          two-phase home resolution           (FR-006, FR-007, FR-008)
└── (everything else unchanged)

tests/
├── test_home_derivation.py        new: the slug table, the reserved name, E-1
├── test_cli_version.py            new: --version, --license, version agreement
├── test_no_optional_dependencies.py  new: R-1/R-2 with the imports blocked
├── test_cli_status.py             extended: the five keys, both shapes, R-4
├── test_config.py                 extended: the chain's last term, environments
└── (everything else unchanged)

.github/workflows/tests.yml        new: 3.9-3.13, no extras          (FR-002)
pyproject.toml                     requires-python, dev extra        (FR-001)
README.md                          the four new facts
```

**Structure Decision**: unchanged — one package, one flat `tests/` directory, one workflow. This
feature adds no module and no subpackage; the derivation lives in `config.py` because that is where
the base URL it derives from is resolved, and there must be exactly one place that decides a home.

## Phasing

1. **The floor** (FR-001, FR-002, FR-003) — `requires-python`, the workflow, and the tests that
   make the stdlib path load-bearing. Useful alone: it is the row that proves the design's claim.
2. **The stamp** (FR-004, FR-005) — `__version__`/`__license__` and the two flags. Useful alone.
3. **The address** (FR-006, FR-007, FR-008) — `CLOUD_BASE_URL`, the slug, the two-phase home.
   Depends on nothing above.
4. **The report** (FR-009, FR-010) — the status keys and the startup line, which read phase 3's
   resolution. Depends on 3.
5. **The prose** — README, and the gate green on 3.9 and on the newest interpreter present.

## Complexity Tracking

| Decision | Why needed | Simpler alternative rejected because |
|---|---|---|
| **Two-phase home resolution** (FR-007) instead of one chain | the home decides where the config file is, and the config file can name the base URL the home is derived from — a one-pass chain is circular | "always read `~/.keel/config.json` first" reintroduces one directory for every Keel, which is the failure E-1 exists to prevent; "never read a config file for `base_url`" would silently break the one branch that works today |
| `environment` computed rather than stored | it must be true of whatever URL actually resolved, including a URL that changed since the last run | a stored value goes stale exactly when a founder switches Keels — the moment it matters |
| The running shape's `environment` comes from the **heartbeat's** `base_url` | it describes the process that is running, not the environment a fresh resolution would pick | resolving afresh would let `status` describe a Keel the live runtime is not talking to |
