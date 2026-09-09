# Feature Specification: The runtime that ships inside the skill

**Feature Branch**: `004-shipped-runtime`

**Created**: 2026-09-08

**Status**: Implemented

**Input**: the design of record, keel-cloud `canon/designs/keel-skill-design.md` (2026-09-08) —
§3 what ships and how it is resolved, §4 *Python 3.9 or newer is the one prerequisite*, §6
*Addresses and environments* (§6.2 the cloud default, §6.3 the derived home), §7 the outcome
contract's `environment` key, §9 invariants R-1, R-2, R-4, E-1, E-2, C-10, §12 decisions 2, 4 and
12, §13 **implementation order step 1**, §14 acceptance A-1, A-9, A-10.

This is **step 1 of §13, exactly** — the runtime's whole share of the design, and it ships alone.
The runtime is 2,070 lines of dependency-free Python that from now on travels *inside* the skill
rather than being installed; this spec makes the runtime worth carrying: it runs on the floor
interpreter a founder already has, it says who it is, and it keeps one Keel's credential out of
another Keel's directory.

## Scope

`pyproject.toml`, `keel_runtime/__init__.py`, `keel_runtime/config.py`, `keel_runtime/cli.py`,
`.github/workflows/tests.yml` (new — this repository's first workflow), `README.md`, and five test
modules (three new, two extended). **Out of scope, by name**: `keel disconnect` (spec
`003-keel-disconnect`, another agent's), the Copilot executor and the host-detection table (spec
`005-copilot-executor`), and `CLOUD_BASE_URL`'s real value (§13 **step 8**, blocked on the AWS
deployment design). The scripted and stub executors are **untouched**; no wire shape changes; the
runtime keeps its zero required dependencies.

## User Scenarios & Testing

### User Story 1 - The runtime runs on the interpreter the founder already has (Priority: P1)

A founder on a Mac with the Xcode command-line tools has `/usr/bin/python3` at **3.9.6** and
nothing else. The skill that carries this runtime runs it with the interpreter that ran the
skill's own script. It works — imports, connects, polls — with no `pip install` of anything, and
in particular with neither `keyring` nor `jsonschema` present, because nobody installs an extra
that nothing asks for (R-1, R-2; decisions 2 and 4).

**Why this priority**: every other row of the design assumes it. A runtime that needs 3.10 excludes
the machine the founder is sitting at.

**Independent Test**: the suite green on 3.9 with no third-party package but the test runner.

**Acceptance Scenarios**:

1. **Given** Python 3.9, **When** the suite runs with neither `keyring` nor `jsonschema`
   installed, **Then** it is green, and `requires-python` says `>=3.9`.
2. **Given** an interpreter where importing `keyring` and `jsonschema` raises `ImportError`,
   **When** every module of `keel_runtime` is imported and a completed job's result is validated,
   **Then** the import succeeds, the credential store uses its `0600` file and the **stdlib subset
   validator** does the validating — the shipped path, not a degraded one.
3. **Given** the matrix, **When** any row runs, **Then** it installed no extra, and asserts so
   before running the suite.

---

### User Story 2 - Two Keels never share a credential (Priority: P1)

The founder runs the playground keel-cloud on `:18081` and, later, the real one. Today both write
`~/.keel`, and the playground sets `KEEL_HOME=~/.keel-playground` by hand so a test credential is
never presented to production. The moment a human forgets, one Keel is handed the other's token and
the failure is a 401 that names no cause.

The home now **follows the address**: `~/.keel/<host-slug>/`, derived from the resolved base URL.
`KEEL_HOME` and `--home` still win outright, and become an override rather than a requirement
(E-1, §6.3).

**Why this priority**: it is the one change here that removes a way to lose data — and it is what
lets keel-connect-playground drop `KEEL_HOME` in §13 step 6.

**Independent Test**: connect against two base URLs from one `$HOME` with no `KEEL_HOME` set; two
homes, two credentials, the first untouched.

**Acceptance Scenarios**:

1. **Given** `KEEL_BASE_URL=http://localhost:18081` and no `KEEL_HOME`, **When** the config
   resolves, **Then** the home is `~/.keel/localhost-18081/`.
2. **Given** the same `$HOME` and `KEEL_BASE_URL=http://localhost:18080`, **When** it resolves
   again, **Then** the home is a *different* directory and the first one's credential file is
   untouched.
3. **Given** `KEEL_HOME` or `--home`, **When** anything resolves, **Then** that directory is the
   home, whatever the base URL says — the one way to make two Keels share a home.
4. **Given** nothing at all — no flag, no environment variable, an empty `CLOUD_BASE_URL` —
   **When** `status` runs, **Then** the home is today's `~/.keel`, `environment` is `null`, and
   `status` still exits 0 without a network call (R-4).

---

### User Story 3 - The founder is never left guessing which Keel this is (Priority: P1)

Every reply the skill gives ends with one clause naming the Keel it is talking to. The skill knows
nothing about addresses (X-5), so the runtime must say it: `status` carries `environment` and
`base_url` in both shapes, and `connect` prints the same two facts in its first line, into the log
the skill is already reading (§6.3, §7).

**Why this priority**: it is the key the skill's seven outcome shapes are being rewritten around in
§13 step 3; that step needs this one shipped to read it from.

**Independent Test**: `status` against a fabricated `$KEEL_HOME`, both shapes, with and without a
base URL resolvable.

**Acceptance Scenarios**:

1. **Given** any invocation, **When** `status` runs, **Then** its one line of JSON carries `home`,
   `base_url`, `environment`, `executor` and `executor_on_path`, each always present in both
   shapes (C-10), and exits 0.
2. **Given** a resolved base URL of `http://localhost:18081`, **When** `status` runs, **Then**
   `environment` is `"localhost:18081"`; **Given** the built-in `CLOUD_BASE_URL`, **Then**
   `environment` is `"cloud"`; **Given** nothing resolvable, **Then** `environment` is `null`.
3. **Given** `connect` starting, **When** it prints its first line, **Then** that line is
   `KEEL_ENVIRONMENT=<environment> base_url=<url>` — machine-readable, like `KEEL_USER_CODE=`
   beside it.

---

### User Story 4 - The runtime says which runtime it is (Priority: P2)

There is no version today: `__version__ = "0.1.0"` is the only stamp, `git tag` is empty, and there
is no `--version` (§2). A runtime that travels inside four packagings must be able to answer *which
one are you* on a founder's machine, and the acceptance bed for Windows asserts exactly that
(§10.3 assertion 3).

**Why this priority**: cheap, and every later step (`RUNTIME_VERSION`, the release notes, a bug
report) leans on it.

**Independent Test**: `python3 -m keel_runtime --version` and `--license`, exit 0, one line each.

**Acceptance Scenarios**:

1. **Given** any working directory, **When** `python3 -m keel_runtime --version` runs, **Then** it
   prints `keel-runtime <version>` and exits 0, with no subcommand required.
2. **Given** a `CLOUD_BASE_URL` with a value, **When** `--version` runs, **Then** the same line
   also names that address — §13 step 8's whole edit is the constant.
3. **Given** `--license`, **When** it runs, **Then** it names the licence and states that the
   runtime bundles no third-party code, and exits 0.

### Edge Cases

- **A base URL with no port**: `https://cloud.keel.example` → slug `cloud.keel.example`, no port
  segment. A port *stated* is always kept, even a default one (`:443`), because two URLs that
  differ only by a written port are two configurations and the derivation never guesses.
- **A base URL differing only by scheme**: `http://` and `https://` of the same host and port are
  **one** Keel with a misconfiguration, not two — the scheme is not in the slug (§6.3).
- **Userinfo, path, query**: `http://u:p@example.com:8080/v2?x=1` → `example.com-8080`. No scheme,
  no path, no secret in a directory name.
- **A character outside `[a-z0-9.-]`**: replaced with `-`, so `keel_cloud.internal` →
  `keel-cloud.internal` and an IPv6 literal `[::1]:8080` → `--1-8080`. Ugly is fine; ambiguous is
  not, and nothing outside the class ever reaches the filesystem.
- **A value that sanitises to nothing at all** (`.`, `..`, `---`, an unparseable string with no
  host): no slug is derived and the home falls back to `~/.keel`. A directory named `.` or `..` is
  the one outcome this must never produce.
- **`bin` is reserved**: `~/.keel/bin/` belongs to Keel, so a host that would slug to `bin` becomes
  `bin-keel`. `ls ~/.keel/` on an acceptance run must show host slugs and nothing else (§10.4).
- **A malformed `$KEEL_HOME/config.json`** stays non-fatal, exactly as today.
- **No base URL anywhere and an empty `CLOUD_BASE_URL`**: `connect` keeps today's `SystemExit` with
  its one-line remedy (E-2); `status` still answers, still exits 0.

## Requirements

### Functional Requirements

- **FR-001** `pyproject.toml` says `requires-python = ">=3.9"`. No source change is needed to make
  that true (§4.2, measured): every annotating module already carries
  `from __future__ import annotations`, and there is no `match`, no walrus, no builtin generic in a
  runtime position.
- **FR-002** `.github/workflows/tests.yml` runs the whole suite on **3.9, 3.10, 3.11, 3.12, 3.13**
  on `ubuntu-latest`, plus 3.9 and 3.13 on `macos-latest` and `windows-latest` (§4.2). It installs
  **no extra** — neither `keyring` nor `jsonschema` — and asserts both are unimportable before the
  suite runs, because a matrix that installed them would be testing a configuration nobody has
  (R-2, decision 4). It also runs `--version` and a `status` against a scratch home, so the two
  things a founder's machine does first are exercised on every row.
- **FR-003** The stdlib subset validator is **load-bearing and tested as such**: a test module
  drives `_subset_validate` directly, another asserts `validate_response` takes the stdlib path
  when `jsonschema` is not importable, and a subprocess test imports every module of the package
  with `keyring` and `jsonschema` blocked at the import hook and validates a result through it
  (R-1, R-2). No test may assume either package is present.
- **FR-004** `keel_runtime/__init__.py` carries `__version__` and `__license__`; `pyproject.toml`'s
  `version` must equal `__version__`, asserted by a test. **The constant is the source of truth**,
  not the installed package metadata: the shipped runtime runs from a directory on `PYTHONPATH`
  (§3.2) and is never installed, so `importlib.metadata` would raise for exactly the founder this
  design is for.
- **FR-005** `keel --version` prints one line, `keel-runtime <version>`, and exits 0, with no
  subcommand required; when `CLOUD_BASE_URL` has a value the same line names it. `keel --license`
  prints the licence notice — the SPDX identifier, the copyright line, the URL of the full text,
  and the sentence that the runtime bundles no third-party code — and exits 0. Both work as
  `python3 -m keel_runtime …` and as an installed `keel …`.
- **FR-006** `config.py` gains `CLOUD_BASE_URL`, a module constant **with a placeholder empty
  value** and a comment naming §13 step 8 as the edit that fills it. It is the **last** term of the
  chain `--base-url > KEEL_BASE_URL > $KEEL_HOME/config.json > CLOUD_BASE_URL` (E-2): a flag, an
  environment variable or a config file always outranks it, and when it has a value it is used
  *instead of exiting* — the cloud default. While it is empty, behaviour is today's, `SystemExit`
  and remedy included (§13 step 1).
- **FR-007** **The derived home** (§6.3). `host_slug(base_url)` is the resolved URL's host,
  lowercased, joined to the port with `-` when the URL states one, every character outside
  `[a-z0-9.-]` replaced with `-`, no scheme, no userinfo, no path; `None` when nothing but dots and
  dashes remains. `bin` is reserved and becomes `bin-keel`. The home is resolved in two phases, so
  that the file config can never contradict the directory it lives in:
  1. `--home` or `KEEL_HOME`, if set — that directory, full stop, and its `config.json`
     participates in the base-URL chain as it does today;
  2. otherwise, a base URL from `--base-url`, `KEEL_BASE_URL` or `CLOUD_BASE_URL` gives
     `~/.keel/<host-slug>/`, and *that* home's `config.json` supplies every key **except**
     `base_url` — a derived home's config file may not rename the Keel that named it;
  3. otherwise nothing resolved: the home is today's `~/.keel`, whose `config.json` may still
     supply `base_url` (today's behaviour, unchanged, and the only branch that can reach it).
- **FR-008** `environment_for(base_url)` is `null` when no base URL resolved, `"cloud"` when the
  resolved URL is `CLOUD_BASE_URL`, and `host:port` otherwise — the address as written
  (`localhost:18081`), bracketed for an IPv6 literal, with no port segment when the URL states no
  port. It is an **address, not a host name** in the design's sense, so it is no exception to D5.
- **FR-009** `keel status` gains `home`, `environment`, `executor` and `executor_on_path`, and
  promotes `base_url` to **always present** — the four keys keel-cloud's
  `specs/021-keel-runtime-status/contracts/status-cli-output.md` is amended for in §13 step 2, and
  named here as the design names them. All five are present in **both** shapes (C-10). In the
  running shape `base_url` and `environment` describe the Keel the *running* process connected to
  (the heartbeat's own record); in the not-running shape they describe what would resolve now.
  `executor_on_path` is whether that executor's CLI is on `PATH`; an in-process executor
  (`scripted`, `stub`) is always available and reports `true`. `status` still never exits non-zero
  and never makes a network call (R-4).
- **FR-010** `keel connect` prints, before anything else, one line
  `KEEL_ENVIRONMENT=<environment> base_url=<base_url>`, flushed, in the same machine-readable
  family as `KEEL_USER_CODE=` and `KEEL_VERIFICATION_URI=` (§6.3, §5.3's startup line).
- **FR-011** Tests for every outcome above: a **table of URLs to slugs**; that a local and a cloud
  base URL never share a home (E-1); `CLOUD_BASE_URL` set and empty (E-2); both `status` shapes
  with the five keys; `--version` and `--license`; the R-2 import-blocked subprocess; and
  `pyproject`'s version agreeing with `__version__`. The existing 181 tests stay green. **Exactly
  two existing assertions may change, and only because this feature changes what they assert**:
  `tests/test_cli_status.py`'s two exact-payload comparisons (the new keys — that edit *is* the
  contract change) and `tests/test_config.py`'s `default_home_is_dot_keel` (the derived home *is*
  the new default). Nothing else in the suite is touched.

### Key Entities

- **host slug** — the directory name taken from a resolved base URL's host and port
  (`localhost-18081`). One per Keel.
- **derived home** — `~/.keel/<host-slug>/`, holding one Keel's credential, heartbeat, config and
  job logs. `KEEL_HOME`/`--home` overrides it and is the only way to make two Keels share one.
- **environment** — *which Keel*, named by its address: `"cloud"` or `host:port`, `null` when
  nothing resolved. Never a host in the agent sense, never a named profile — there is no `KEEL_ENV`.

## Success Criteria

- **SC-001** `python -m pytest` (and `python3 -m unittest discover -s tests -t .`) green on **3.9**
  with neither `keyring` nor `jsonschema` installed, and green on the newest Python present.
- **SC-002** The suite grows: 181 tests before, more after, and every FR above has one.
- **SC-003** `python3 -m keel_runtime --version` and `--license` exit 0 on the founder's
  `/usr/bin/python3` (3.9.6), and `python3 -m keel_runtime status --home <temp>` prints exactly one
  line of JSON carrying the five keys of FR-009 (§10.3 assertion 3's local half).
- **SC-004** With one `$HOME` and no `KEEL_HOME`, two base URLs resolve to two different homes
  (A-9's mechanism, short of the live approval the founder walks).
- **SC-005** The scripted executor and everything else keep working: no test outside
  `tests/test_cli_status.py` and `tests/test_config.py` needed a change.

## Assumptions

- **Apple's `/usr/bin/python3` is 3.9.6** and is the floor (§4.1, measured 2026-09-08). Homebrew's
  3.9.19 stands in for it in the local venv used to run the suite; both are 3.9.
- **`PyYAML` is a test-only dependency and always was**: `tests/test_generate_bundled_script.py`
  imports `tools/generate_bundled_script.py`, which imports `yaml`. It is declared here as a `dev`
  extra so the matrix can install it by name. It is **not** an extra of the runtime and no module
  under `keel_runtime/` imports it — R-2 is about `keyring` and `jsonschema`, and the assertion in
  the workflow names those two.
- **The licence is Apache-2.0**, the identifier the design's own Spec Kit manifest declares for the
  packaging that carries this runtime (§8.4). **This repository holds no `LICENSE` file yet** —
  neither does any sibling — so `--license` names the identifier and points at the canonical text
  rather than quoting a file that does not exist. Adding the file is the founder's call and is
  listed as an open item in `tasks.md`.
- **keel-cloud's status contract is being amended in parallel** (§13 step 2, another agent's). This
  spec implements the four keys as the *design* names them; if the contract file lands naming them
  differently, the contract wins and this is a follow-on edit.
- **Migration is nil** (§6.3): no production data, no release, no founder but the founder. The one
  visible effect is one extra device approval on the first run after this lands, and stale files at
  the old `~/.keel` root that can be deleted by hand. No migration code is written.
