# Feature Specification: The way out — `keel disconnect`

**Feature Branch**: `003-keel-disconnect`

**Created**: 2026-09-08

**Status**: Implemented (first pass — the goodbye's seam only, not its call)

**Input**: the design of record, keel-cloud `canon/designs/keel-disconnect-design.md` (2026-09-08)
— §1 the one sentence, §3 the command and its four outcomes, §3.1 the flow, §3.2 exit 0 and
idempotence, §3.3 the signal and the escalation bound, §3.4 the credential is never touched, §4.2
where the goodbye goes and where it must not, §6 the edge cases, §7 invariants D1–D10 and G1–G6,
§8.1 the tests, §9 decisions 1, 3, 4, 6, 11, 13, and §10 **implementation order step 2**. The home
it resolves is the one keel-cloud `canon/designs/keel-skill-design.md` §6.3 defines and this
repository's spec `004-shipped-runtime` FR-007 built.

This is **step 2 of §10, exactly**, and nothing else. There is a door into Keel — a founder says
"keel connect" and a runtime starts — and no door out: the only way to stop that process is
`kill <pid>` in a terminal, which is precisely the terminal work the skill exists to spare them.
This spec is the door out. It ships alone and is immediately useful: it is what keel-e2e-eval's
`make down` should have been calling all along.

## Scope

`keel_runtime/disconnect.py` (new), `keel_runtime/cli.py`, `keel_runtime/poller.py` (one line),
`README.md`, `contracts/disconnect-cli-output.md` (new, in this feature's own directory) and two
new test modules. **Out of scope, by name**:

- **The goodbye's call itself** — §10 step 4, the second pass, blocked on keel-cloud spec
  `033-agent-session-goodbye` existing to be called. What lands here is the **seam** it goes in
  (`_say_goodbye` in `_run_connect`), a no-op today and tested as one.
- **keel-cloud's route, column and job cancel** (§4.3, §6e) — step 3, another repository's.
- **keel-connect-skill's `scripts/keel_disconnect.py`, its contract and SKILL.md** (§5) — step 5,
  another repository's. Nothing in this repository knows the skill exists.
- **keel-e2e-eval's S-001 tail and `make down`** (§8.4) — step 6.
- **`--drain`** (decision 2), **`keel forget` / `--forget`** (decision 3, §3.4), a **`--pid` flag
  or a start-time fingerprint against pid reuse** (decision 11, §6c), and **`--all-homes`** (§6b).
  Each is deferred by the design by name, and none is built here.

No wire shape changes, no network call is added, and the runtime keeps its zero required
dependencies.

## User Scenarios & Testing

### User Story 1 - The founder can stop what they started (Priority: P1)

A founder said "keel connect" an hour ago. A runtime has been polling ever since, in a process
they cannot see, started detached by a skill. They want it to stop. Today the answer is "find the
pid and `kill` it"; after this, the answer is one command that finds the runtime this home is
running, asks it to stop the way Ctrl+C would, waits, proves it is gone, and says so in one line
of JSON.

**Why this priority**: it is the whole feature. Everything else here is a case of it.

**Independent Test**: a real child process on a fabricated home; `disconnect` stops it and reports
`stopped` with the pid it signalled.

**Acceptance Scenarios**:

1. **Given** a heartbeat naming a live process that honours `SIGTERM`, **When** `disconnect` runs,
   **Then** the process is gone, the outcome is `stopped` with `signal: "SIGTERM"`, a `pid` and a
   `waited_ms`, the heartbeat file is gone, and the exit code is 0.
2. **Given** a process that ignores `SIGTERM`, **When** `disconnect` runs, **Then** it escalates
   to `SIGKILL` after the grace, the outcome is `stopped` with `signal: "SIGKILL"` and a
   `waited_ms` no smaller than the grace (D5).
3. **Given** a process that survives both signals, **When** the bound passes, **Then** the outcome
   is `timeout` with the pid and `waited_ms`, and **the heartbeat file is left in place** (D6).

---

### User Story 2 - Nothing running is a normal answer, twice over (Priority: P1)

The founder says "disconnect" against a home that has nothing on it — because they already did,
because they never connected, or because the runtime died in the night and left a file behind.
None of those is an error, and none of them leaves anything behind afterwards.

**Why this priority**: idempotence is what makes the command safe to put in a teardown script, a
hook, or a second reply to a nervous founder.

**Independent Test**: run it twice; the second run is `not_running`.

**Acceptance Scenarios**:

1. **Given** a home with no heartbeat file, **When** `disconnect` runs, **Then** the outcome is
   `not_running` and exit 0.
2. **Given** a heartbeat that is unreadable, malformed JSON, or short a required field, **When**
   `disconnect` runs, **Then** the outcome is `not_running` — one answer for all four cases,
   exactly as `status` treats them (D1).
3. **Given** a heartbeat naming a pid that is not alive, **When** `disconnect` runs, **Then** the
   outcome is `stale_pid_cleared` with that pid, the file is removed, and **no signal is sent to
   anything** (D2).
4. **Given** any successful stop, **When** `disconnect` runs a second time, **Then** the outcome
   is `not_running` (D10).

---

### User Story 3 - Stopping a process never forgets a machine (Priority: P1)

The founder stops Keel for the afternoon. When they say "keel connect" tomorrow it must reconnect
with no device code and no browser — because disconnect stopped a process, it did not un-approve a
device.

**Why this priority**: the opposite behaviour is unrecoverable by the founder without the browser,
and it would be discovered a day later, by someone who has forgotten what they ran.

**Independent Test**: a `credentials.json` in the home is byte-identical after every outcome.

**Acceptance Scenarios**:

1. **Given** a home with a stored credential, **When** any outcome of `disconnect` occurs, **Then**
   `credentials.json` is unchanged, no keyring entry is touched, and nothing else in the home is
   removed but the heartbeat (D7).

---

### User Story 4 - The founder is told which Keel they just disconnected from (Priority: P2)

The founder runs a playground Keel on `:18081` and, later, a real one, each with its own derived
home. "Disconnected" without an address is half an answer: it does not say which of the two
stopped.

**Why this priority**: it is the same reason spec `004-shipped-runtime` put `environment` and
`base_url` on `status`. The skill that will relay this line carries no address of its own (§6.3,
X-5) and can only report what the runtime hands it.

**Independent Test**: `disconnect --home` against a derived home; the line names that home and the
Keel the heartbeat records.

**Acceptance Scenarios**:

1. **Given** any outcome, **When** `disconnect` runs, **Then** the same line also carries `home`,
   `base_url` and `environment`, always present, resolved exactly as `status` resolves them.
2. **Given** a readable heartbeat, **When** the line is printed, **Then** `base_url` and
   `environment` describe the Keel **the stopped process was talking to** (the heartbeat's own
   record), not what a fresh resolution would pick now — the same rule as `status`'s running shape.
3. **Given** `--home`, `KEEL_HOME`, `--base-url`, `KEEL_BASE_URL` or none of them, **When**
   `disconnect` resolves its home, **Then** it resolves the identical directory `status` resolves
   from the same inputs (spec 004 FR-007).

---

### User Story 5 - The runtime has somewhere to say goodbye from (Priority: P3)

When keel-cloud gains `POST /v2/agent-sessions/{id}/disconnect`, the runtime's last act will be
one bounded, best-effort call to it, so the founder's own screen stops saying *Agent connected* in
about four seconds instead of up to ninety. That call is the second pass. What this pass owes it
is the **place it goes**, chosen correctly: not in the signal handler, which runs on the main
thread's stack wherever that thread happens to be (usually inside the long-poll's `urlopen`), but
in `_run_connect`, after the stack has unwound and the heartbeat is already gone.

**Why this priority**: it is a hook and one call site. It is here rather than in the second pass
because *where* it goes is a design decision (§4.2) and the ordering it guarantees (G3) is cheaper
to establish now than to retrofit around a working call.

**Independent Test**: with a client that has no goodbye method — today's `CloudClient` — nothing
is called, nothing is sent, and `connect` exits exactly as it does now.

**Acceptance Scenarios**:

1. **Given** today's `CloudClient`, **When** `connect`'s poll loop returns, **Then** the seam runs,
   makes no network call of any kind, and the exit code and output are unchanged.
2. **Given** a client that does have the goodbye, **When** the seam runs, **Then** it is called
   once with this runtime's agent session id and access token, **after** the heartbeat has been
   removed (G3).
3. **Given** a goodbye that raises, times out, or answers 404, **When** the seam runs, **Then** the
   exit code is 0 and nothing else changes (G1).
4. **Given** a run interrupted during device authorization — no agent session — **When** the seam
   runs, **Then** nothing is called at all (G6).

### Edge Cases

- **A runtime started by hand, not by a skill.** No special case: the heartbeat, not the launcher,
  is what "the runtime on this home" means. The founder's own terminal simply returns to a prompt,
  exactly as if they had pressed Ctrl+C in it (§6a).
- **Two homes, two Keels.** `--home` / `KEEL_HOME` / the derived home partitions everything. A
  disconnect in the playground can never reach the real runtime (§6b). **"Disconnect everything" is
  not a thing this command does** — it knows one home; a founder running two must say which.
- **Pid reuse.** Accepted and unmitigated (decision 11). Disconnect signals only a pid it read from
  *this home's own* heartbeat and never one a caller supplied — there is deliberately no `--pid`
  flag — and it is the same exposure `status` already takes when it reports `running: true` for a
  recycled pid.
- **A stale heartbeat with a live pid.** Signalled like any other. A staleness guard is a
  **tempting wrong guard**: the heartbeat is written once per poll cycle and a runtime executing a
  300-second `claude` job writes none for 300 seconds — six times the 50-second default — so the
  guard would refuse to stop precisely the runtime a founder most wants stopped (§6c).
- **A job in flight is abandoned** — not finished, not failed. No `/complete`, no `/fail`, nothing
  said (D4). That is what Ctrl+C already does, and the job's fate is keel-cloud's business (§3.3,
  §6e). Draining is deferred (decision 2).
- **The heartbeat vanishes between the signal and the check** — because the runtime's own handler
  removed it, which is the common path. Nothing to remove; the outcome is unchanged.
- **The heartbeat is rewritten with a different pid** between the signal and the check: the file
  survives, untouched (D3). Whatever wrote it is not the process that was just stopped.
- **Windows.** `os.kill` there terminates unconditionally rather than delivering a catchable
  signal, so the `SIGTERM` step already stops the process and the escalation is unreachable in
  practice. The outcome vocabulary does not change.
- **A pid this user may not signal** (`PermissionError`): `pid_alive` already reports it alive, and
  the `os.kill` raises. That is a `timeout`-shaped world with no wait in it; it is reported as
  `timeout`, with the heartbeat left in place, rather than as a crash.

## Requirements

### Functional Requirements

- **FR-001** `keel disconnect [--home PATH] [--base-url URL]` exists as a subcommand of the same
  CLI, in `python3 -m keel_runtime` and in an installed `keel`. `--home` follows the same
  precedence as `connect` and `status` (flag > `KEEL_HOME` > the home derived from the resolved
  base URL > `~/.keel`), through the same `config.load_status_config`, and resolves the identical
  directory `status` resolves from the same inputs. `--base-url` is accepted for one reason: since
  spec 004 the home **follows the address**, so naming the address is a way of naming the home, and
  a caller that says which Keel it means should not have to compute a slug to say which home it
  means. No other flag is accepted.
- **FR-002** The flow is the design's §3.1, exactly: read the heartbeat; `not_running` if there is
  none (D1); if the pid is not alive, remove the file and answer `stale_pid_cleared` **without
  signalling anything** (D2); otherwise `SIGTERM`, wait up to `grace`, and if the pid is gone
  answer `stopped` with `signal: "SIGTERM"`; else `SIGKILL`, wait up to `grace + kill_after`, and
  if the pid is gone answer `stopped` with `signal: "SIGKILL"`; else `timeout` (D5).
- **FR-003** `grace` is **10.0s** and `kill_after` is **5.0s** — 15 seconds worst case (decision
  13). They are module constants, not flags: a founder waiting on a cursor should not have to
  choose a number, and a caller that needs different ones is a test, which passes them as keyword
  arguments to the seam of FR-009.
- **FR-004** The heartbeat is removed **only while it still names the pid that was signalled**
  (D3), and on `timeout` it is **left in place** (D6) — a process that is still polling must never
  read as not running, because that is the one lie that produces two runtimes on one home.
- **FR-005** Exactly **one line of JSON on stdout**, newline-terminated, nothing else, and **exit
  0 always** (D8). `timeout` is the one outcome a caller must treat as a failure and it says so by
  name (decision 6). A genuine usage error — an unknown flag — is argparse's own non-zero exit with
  its message on stderr, and is not one of these shapes.
- **FR-006** `disconnect` makes **no network call at all** (D9), touches **no credential** — not
  `credentials.json`, not the keyring (D7) — and removes nothing in the home but the heartbeat.
- **FR-007** It is **idempotent**: a second run against the same home is `not_running`, and a home
  that has never connected is `not_running`. There is no state disconnect keeps between runs (D10).
- **FR-008** Every line also carries `home`, `base_url` and `environment`, always present, resolved
  exactly as spec 004 FR-009 resolves them for `status`, with the same rule that a readable
  heartbeat's own `base_url` wins — it describes the Keel the stopped process was talking to.
  `executor` and `executor_on_path` are **not** carried: no executor takes part in a disconnect,
  and a key that is always answered from a fresh resolution would describe a process that is no
  longer there.
- **FR-009** The command is written around the seam §8.1 names, so that every outcome — including
  the two no real process can produce on demand — is a fast unit test:
  `disconnect(home, *, grace, kill_after, kill, alive, clock, sleep) -> dict`.
- **FR-010** **The goodbye's seam** (§4.2). `_run_connect` calls `_say_goodbye(client, state,
  config)` after `run_loop` returns and therefore after the shutdown handler has removed the
  heartbeat (G3), never inside the handler. It calls nothing when there is no agent session (G6).
  Today it finds no goodbye on `CloudClient` and returns having done nothing — the second pass adds
  the client method and this call site starts working, with no edit here. Every exception it could
  raise is swallowed; it never changes the exit code, the output, or `disconnect`'s outcome (G1),
  and it is bounded to one call with a 2s timeout and no retry when it exists (G2).
- **FR-011** `run_loop` returns the `RuntimeState` it finished with, and `_run_connect` uses that
  one for the goodbye. Found while writing FR-010: `run_loop` **rebinds `state`** when a credential
  expires mid-run (`_reauthorize`), so the caller's local variable can name an agent session that
  is already dead. One `return` makes the seam address the session that was actually live.
- **FR-012** The stable, external contract is
  [`contracts/disconnect-cli-output.md`](contracts/disconnect-cli-output.md), written in the
  five-part shape keel-cloud's `specs/021-keel-runtime-status/contracts/status-cli-output.md` uses
  — the bold lede naming it the stable contract, `## Invocation`, `## Output shapes (exhaustive)`,
  `## Guarantees a caller may rely on`. It lives **here**, in this repository, because the command
  is this repository's and keel-connect-skill's own contract (§5.2) is a different file, one level
  up, that this one does not constrain.
- **FR-013** Tests for every outcome above, per §8.1: `stopped` via `SIGTERM` and via `SIGKILL`
  against **real child processes** (the escalation case a real child that installs
  `signal.SIG_IGN`); `not_running` for an empty home and for a malformed and a short heartbeat;
  `stale_pid_cleared` with a fake `kill` asserting nothing was signalled; `timeout` injected
  through the seam with no real waiting; idempotence; the untouched credential; D3's rewritten
  heartbeat; `--home` precedence mirroring `test_cli_status.py` and asserted **equal to what
  `status` resolves**; and the whole module under a `urlopen` that raises (D9). Plus the goodbye
  seam's four assertions (G1, G3, G6, and the no-op that is today's truth).

### Key Entities

- **outcome** — the one word the JSON line leads with, and the whole answer: `stopped`,
  `not_running`, `stale_pid_cleared` or `timeout`.
- **grace** — how long `SIGTERM` is given before escalation (10s).
- **escalation** — `SIGKILL` after `SIGTERM` has had its grace, bounded by `kill_after` (5s).
- **stale pid** — a heartbeat naming a process that is not alive: the trace of a runtime that died
  without running its handler. `status` has always reported it and left the file lying there;
  `disconnect` is the thing that finally cleans it up.
- **goodbye** — the runtime's last act, and not this command's: one bounded, best-effort call that
  ends its own agent session. Only its seam lands here.

## Success Criteria

- **SC-001** `python -m pytest` green on **3.9** with neither `keyring` nor `jsonschema`
  installed, and green on the newest Python present.
- **SC-002** The suite grows: 229 tests before this feature, more after, and every FR above has
  one.
- **SC-003** `python3 -m keel_runtime disconnect --home <temp>` prints exactly one line of JSON and
  exits 0 against a home with nothing on it, with no network available.
- **SC-004** Every outcome of `disconnect` leaves a `credentials.json` in the home byte-identical.
- **SC-005** Nothing outside `keel_runtime/disconnect.py`, `keel_runtime/cli.py` and one line of
  `keel_runtime/poller.py` changes in the runtime, and no existing test needed an edit.

## Assumptions

- **The runtime already honours the signal.** `_install_heartbeat_shutdown_handlers` (spec 021
  FR-003) removes the heartbeat and raises `KeyboardInterrupt` on `SIGINT` and `SIGTERM`, so a
  `keel disconnect` is, to the runtime, indistinguishable from Ctrl+C. No new shutdown path is
  built and none is wanted: this command is a caller of a path that already exists, plus a wait and
  a proof.
- **A job in flight is keel-cloud's problem, and it is a known open one.** A `RUNNING` job whose
  runtime went away stays `RUNNING` forever today — there is no lease, no TTL and no sweeper
  anywhere in that application (§6e). Disconnect does not create that gap and does not close it;
  the goodbye's second effect (step 3, keel-cloud) is where it closes.
- **Migration is nil.** No production data, no release, no founder but the founder. Nothing here
  reads or writes anything that existed before it.
- **keel-connect-skill's contract is a different file.** The skill maps these four outcomes onto
  six of its own (`stopped` → `disconnected`, `timeout` → `did_not_stop`, plus its two layer
  failures) in §5.2, in step 5, which is not this spec's.
