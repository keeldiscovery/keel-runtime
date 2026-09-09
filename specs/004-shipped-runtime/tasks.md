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

- [x] T015 `README.md`: the 3.9 floor and the matrix, `--version`/`--license`, the derived home and
      the slug rule, `CLOUD_BASE_URL` in the precedence table, and the new `status` shapes.
- [x] T016 Gate green on 3.9 and on 3.13 (SC-001, SC-002); commits in the house style with the
      trailers; merge to `master` and push (the founder asked for it tonight).

## Phase 6: The address, for real

- [x] T017 §13 step 8 — keel-cloud deployed at `https://app.keeldiscovery.com` (spec 034, live
      2026-09-09; `/v2/setup` answers 200): `keel_runtime/config.py`'s `CLOUD_BASE_URL` given that
      value; every test that pinned the placeholder updated (the empty-constant behaviour,
      `--version`'s output, the slug `app.keeldiscovery.com`, `environment` = `cloud` for that
      host); `README.md` and this file updated; `python -m keel_runtime status` and `connect` run
      for real with no environment configured (the latter stopped before approval, no credential
      left behind); `python -m pytest` green on 3.9 and 3.13 (366).

## Open items (not this spec's)

- **A `LICENSE` file** — `--license` names Apache-2.0, the identifier the design's own Spec Kit
  manifest declares for the tree that carries this runtime (§8.4). No sibling repository holds a
  licence file today. Adding the text is the founder's call.
- **keel-cloud's status contract** — `specs/021-keel-runtime-status/contracts/status-cli-output.md`
  is amended for these four keys plus the `base_url` promotion by §13 step 2, which is keel-cloud's
  and was not touched here.

## Discovered

- **The suite could not run on 3.9 at all before this spec — for a reason that had nothing to do
  with 3.9.** `tests/test_generate_bundled_script.py` imports `tools/generate_bundled_script.py`,
  which imports `yaml`, and `PyYAML` was declared nowhere: it happened to be present in the
  founder's default 3.12 interpreter and in no other. A fresh 3.9 venv collected 180 tests and one
  collection error. Declaring the `dev` extra (T001) is what made "green on the floor" a statement
  anybody can reproduce, and it is why the matrix installs `.[dev]` rather than a bare `pytest`.
  Nothing under `keel_runtime/` imports `yaml`, so R-2 is untouched — and the workflow asserts the
  two names R-2 actually governs rather than trusting the extra's contents.

- **The home resolution is circular unless it is two-phase, and the design does not say which way
  to cut it.** §6.3 derives the home from the *resolved* base URL, while §6.2's chain resolves the
  base URL partly *from a file inside the home*. FR-007 cuts it: the file participates in the
  base-URL chain only where it cannot contradict the directory it sits in — an explicit
  `KEEL_HOME`/`--home`, or the `~/.keel` fallback that is reached only when nothing else resolved.
  A derived home's `config.json` may still set every other key; it may not rename its own Keel. The
  practical consequence is that today's one working branch (`~/.keel/config.json` naming a
  `base_url`, with an empty `CLOUD_BASE_URL`) behaves exactly as it does today, which is what §13
  step 1 asks for.

- **`_resolve_home` had to stop reading `Path.home()` at import time.** `DEFAULT_HOME` was a module
  constant evaluated when `config` was first imported, so a test that sets `HOME` to a temporary
  directory — which is the only honest way to test a derivation rooted at `~/.keel` — saw the real
  one. It is now `_default_home_root()`, called at resolution time; `DEFAULT_HOME` survives as a
  module attribute because `executor.py` imports it for its per-job directory fallback.

- **`environment` in the running shape is the heartbeat's, not a fresh resolution's.** The two can
  disagree — a founder who edits `KEEL_BASE_URL` in a second shell while a runtime is up would
  otherwise be told the live runtime is talking to a Keel it has never contacted. The heartbeat
  already records the `base_url` the process actually connected to; the running shape derives
  `environment` from that, and the not-running shape from what would resolve now. Both are stated
  in FR-009 and asserted in `tests/test_cli_status.py`.

- **`executor_on_path` is `true` for `scripted` and `stub`.** C-10 requires the key in both shapes,
  and those two executors have no CLI to find: they run in this process. Reporting `false` would
  read as "broken" on a healthy deterministic run — the same objection the design raises against
  `claude_on_path`. The mapping from executor name to binary is one dict in `cli.py` holding one
  entry (`claude-code` -> `claude`); spec 005 adds `copilot` to it when the executor it names
  exists.

- **A slug that sanitises to nothing had to be refused explicitly.** `.` and `..` are legal outputs
  of "replace every character outside `[a-z0-9.-]`" and are catastrophic as directory names. The
  rule implemented is: sanitise, then refuse the slug entirely if nothing but dots and dashes
  remains, falling back to `~/.keel`. Leading and trailing dashes are otherwise **kept**, so the
  IPv6 literal `[::1]:8080` slugs to `--1-8080` rather than colliding with `1-8080`.

- **The slug table, as implemented** (`tests/test_home_derivation.py` asserts exactly this):

  | resolved base URL | `~/.keel/<slug>/` | `environment` |
  |---|---|---|
  | `http://localhost:18081` | `localhost-18081` | `localhost:18081` |
  | `http://localhost:18080` | `localhost-18080` | `localhost:18080` |
  | `http://127.0.0.1:1` | `127.0.0.1-1` | `127.0.0.1:1` |
  | `https://cloud.keel.example` | `cloud.keel.example` | `cloud.keel.example` |
  | `https://Cloud.Keel.Example/v2/` | `cloud.keel.example` | `cloud.keel.example` |
  | `http://cloud.keel.example` | `cloud.keel.example` | `cloud.keel.example` |
  | `https://cloud.keel.example:443` | `cloud.keel.example-443` | `cloud.keel.example:443` |
  | `http://u:pw@example.com:8080/v2?x=1` | `example.com-8080` | `example.com:8080` |
  | `https://keel_cloud.internal` | `keel-cloud.internal` | `keel_cloud.internal` |
  | `http://[::1]:8080` | `--1-8080` | `[::1]:8080` |
  | `http://bin` | `bin-keel` | `bin` |
  | `localhost:18081` (no scheme) | `localhost-18081` | `localhost:18081` |
  | `` / `.` / `..` / `http://` | *(none — `~/.keel`)* | `null` |
  | the value of `CLOUD_BASE_URL` | its own host's slug | `cloud` |

  Two rows are worth naming. The scheme is absent from both columns, so `http://` and `https://` of
  one host are one Keel (§6.3). And a schemeless `localhost:18081` lands on the same slug as the
  `http://` form — `urlsplit` finds no host in it, so the whole string is sanitised, and the
  sanitisation of `localhost:18081` is `localhost-18081` by the same rule that joins a port with a
  dash. That agreement is a happy accident of the rule, not a special case, and the table pins it.

- **`environment` needed the same refusal as the slug, and did not have it at first.** A base URL
  of `.` produced no slug (the guard against handing `.` or `..` to the filesystem) but an
  `environment` of `"."` -- a null answer and a nonsense answer for one input. The refusal moved
  down into `_split_address`, so a value that is nothing but dots and dashes is not an address at
  all, in either column. The table's last row pins it.

- **Two existing assertions changed, and only two.** `tests/test_cli_status.py`'s two exact-payload
  comparisons (the new keys -- that edit *is* the contract change), and `tests/test_config.py`'s
  `test_default_home_is_dot_keel_when_nothing_names_one`, which asserted `~/.keel` for a run that
  names a base URL and no home: the derived home is the default now, so it was renamed to
  `test_the_home_follows_the_address_when_nothing_names_one` and asserts the derivation, with the
  `~/.keel` fallback moving to `tests/test_home_derivation.py` where it belongs.

- **The R-2 blocker was verified against an interpreter that *has* the extras.** A test that blocks
  `keyring` and `jsonschema` proves nothing on a machine where neither is installed -- which is
  every machine here. So both were installed into a scratch 3.13 venv and the suite run again: 229
  green, with `test_the_two_names_really_are_unimportable_in_that_subprocess` still passing, which
  is the assertion that the blocker itself works. They were then removed. The suite is green both
  with and without them, and the matrix runs the configuration founders actually have.

- **The status subprocess tests now run with a cleaned environment.** They inherited the caller's,
  and keel-connect-playground exports `KEEL_BASE_URL` into every session it hosts -- so the new
  `base_url`/`environment` keys would have been asserted against whatever shell happened to launch
  the suite. Each subprocess now gets `KEEL_*` stripped and `HOME`/`USERPROFILE` pointed at a
  temporary directory, which is also what makes the derived-home assertions honest.

- **`--version` and `--license` are top-level flags, not subcommands, and had to survive
  `required=True` subparsers.** They do: argparse runs an optional's action as it consumes the
  argument, and both actions print and raise `SystemExit(0)` before the missing-subcommand check at
  the end of `parse_args`. `main()` therefore still returns an `int` on every path that returns at
  all, and the tests assert the exit code and the single line through a real subprocess, which is
  what `python3 -m keel_runtime --version` does on the Windows bed (§10.3 assertion 3).
