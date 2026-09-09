# Tasks: The runtime that ships inside the skill

**Input**: [spec.md](spec.md) (FR-001..011, SC-001..005), [plan.md](plan.md), and keel-cloud
`canon/designs/keel-skill-design.md` §3, §4, §6, §7, §9, §13 step 1.

**Rules**: standard library only under `keel_runtime/`; the scripted and stub executors untouched;
no wire change; `status` never exits non-zero and never calls the network (R-4). Out of scope by
name: `keel disconnect` (spec 003), the Copilot executor and host detection (spec 005),
`CLOUD_BASE_URL`'s real value (§13 step 8). **Gate**: `python -m pytest` green on Python 3.9 with
neither `keyring` nor `jsonschema` installed, and on the newest interpreter present.

## Phase 1: The floor

- [x] T001 `pyproject.toml`: `requires-python = ">=3.9"` (FR-001), and a `dev` extra naming the
      test-only dependencies (`pytest`, `PyYAML`) so the matrix installs them by name and nothing
      else.
- [x] T002 `.github/workflows/tests.yml`: 3.9-3.13 on `ubuntu-latest`, 3.9 and 3.13 on
      `macos-latest` and `windows-latest`; install the `dev` extra only; **assert `keyring` and
      `jsonschema` are unimportable** before the suite; run the suite, `--version` and a `status`
      against a scratch home (FR-002, R-1, R-2).
- [x] T003 `tests/test_no_optional_dependencies.py`: a subprocess whose import hook raises
      `ImportError` for `keyring` and `jsonschema`, importing every module of the package,
      exercising the `0600` credential file and validating a result through the **stdlib subset
      validator** (FR-003, R-1, R-2).
- [x] T004 `tests/test_response_validator.py`: the subset validator driven directly and asserted to
      be the path `validate_response` takes when `jsonschema` is not importable — load-bearing, not
      incidental (FR-003).

## Phase 2: The stamp

- [x] T005 `keel_runtime/__init__.py`: `__version__`, `__license__` and the licence notice
      constants (FR-004).
- [x] T006 `keel_runtime/cli.py`: `--version` and `--license` as top-level flags needing no
      subcommand, one line each, exit 0; `--version` names `CLOUD_BASE_URL` when it has one
      (FR-005).
- [x] T007 `tests/test_cli_version.py`: both flags as real subprocesses, the `CLOUD_BASE_URL`
      variant, and `pyproject`'s `version` agreeing with `__version__` (FR-004, FR-005).

## Phase 3: The address

- [x] T008 `keel_runtime/config.py`: `CLOUD_BASE_URL` with a placeholder empty value and the
      comment naming §13 step 8; last term of the chain; the `SystemExit` kept for an empty
      constant (FR-006, E-2).
- [x] T009 `keel_runtime/config.py`: `host_slug`, `derive_home`, `environment_for`, the reserved
      `bin`, and the two-phase home resolution of FR-007 (§6.3, E-1).
- [x] T010 `tests/test_home_derivation.py`: the table of URLs to slugs, the reserved name, the
      overrides, the `~/.keel` fallback, and two base URLs from one `$HOME` never sharing a home
      (FR-007, FR-008, FR-011, E-1).
- [x] T011 `tests/test_config.py`: `CLOUD_BASE_URL` set and empty, the chain's order around it, and
      `environment` for each flavour (FR-006, FR-008).

## Phase 4: The report

- [x] T012 `keel_runtime/cli.py` `_run_status`: `home`, `environment`, `executor`,
      `executor_on_path` and an always-present `base_url` in **both** shapes; still exit 0, still no
      network (FR-009, C-10, R-4).
- [x] T013 `keel_runtime/cli.py` `_run_connect`: the `KEEL_ENVIRONMENT=<env> base_url=<url>`
      startup line, flushed, before anything else (FR-010).
- [x] T014 `tests/test_cli_status.py`: both shapes with the five keys, the no-base-URL case, and
      the derived-home case (FR-009, FR-011).

## Phase 5: The prose and the gate

- [ ] T015 `README.md`: the 3.9 floor and the matrix, `--version`/`--license`, the derived home and
      the slug rule, `CLOUD_BASE_URL` in the precedence table, and the new `status` shapes.
- [ ] T016 Gate green on 3.9 and on 3.13 (SC-001, SC-002); commits in the house style with the
      trailers; merge to `master` and push (the founder asked for it tonight).

## Open items (not this spec's)

- **`CLOUD_BASE_URL`'s real value** — §13 step 8, blocked on keel-cloud's and keel-web's AWS
  deployment design. The constant, its comment and the test that proves a set constant is used
  instead of exiting are all here; only the string is missing.
- **A `LICENSE` file** — `--license` names Apache-2.0, the identifier the design's own Spec Kit
  manifest declares for the tree that carries this runtime (§8.4). No sibling repository holds a
  licence file today. Adding the text is the founder's call.
- **keel-cloud's status contract** — `specs/021-keel-runtime-status/contracts/status-cli-output.md`
  is amended for these four keys plus the `base_url` promotion by §13 step 2, which is keel-cloud's
  and was not touched here.

## Discovered

*(filled in as the work goes.)*
