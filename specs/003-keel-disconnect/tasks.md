# Tasks: The way out — `keel disconnect`

**Input**: [spec.md](spec.md) (FR-001..013, SC-001..005), [plan.md](plan.md),
[contracts/disconnect-cli-output.md](contracts/disconnect-cli-output.md), and keel-cloud
`canon/designs/keel-disconnect-design.md` §3, §4.2, §6, §7, §8.1, §9, §10 step 2.

**Rules**: standard library only under `keel_runtime/`; one line of JSON on stdout and exit 0,
always; no network call; no credential touched; 15 seconds worst case. Out of scope by name: the
goodbye's **call** (§10 step 4, blocked on keel-cloud spec 033), keel-cloud's route and column
(step 3), keel-connect-skill's `scripts/keel_disconnect.py` and SKILL.md (step 5), keel-e2e-eval's
S-001 tail and `make down` (step 6), `--drain`, `keel forget`, a `--pid` flag and `--all-homes`
(decisions 2, 3, 11; §6b). **Gate**: `python -m pytest` green on Python 3.9 with neither `keyring`
nor `jsonschema` installed, and on the newest interpreter present.

## Phase 1: The contract

- [x] T001 `specs/003-keel-disconnect/contracts/disconnect-cli-output.md`: the four shapes, the
      three address keys, the invocation and the nine guarantees, in the five-part shape
      keel-cloud's `status-cli-output.md` uses (FR-012).
- [x] T002 `spec.md` and `plan.md`: the five user stories, FR-001..013, the invariant table, and
      what is out of scope by name.

## Phase 2: The flow

- [x] T003 `keel_runtime/disconnect.py`: `disconnect(home, *, grace, kill_after, kill, alive,
      clock, sleep)` — the design's §3.1 steps in order, the four outcomes, `_remove_if_still_ours`
      (D3), the heartbeat left in place on `timeout` (D6) (FR-002, FR-003, FR-009).
- [x] T004 `tests/test_cli_disconnect.py`: `stopped`/`SIGTERM` against a real child that takes the
      default disposition, and against one that installs the runtime's own handler shape and
      removes its heartbeat on the way out (FR-013).
- [x] T005 `tests/test_cli_disconnect.py`: `stopped`/`SIGKILL` against a real child that installs
      `signal.SIG_IGN` for `SIGTERM`, with a shortened grace so the test is fast; `waited_ms >=`
      the grace (D5).
- [x] T006 `tests/test_cli_disconnect.py`: `not_running` for an empty home, a malformed heartbeat
      and one short a required field — all three identical (D1); `stale_pid_cleared` with a
      recording fake `kill` asserting **nothing was signalled** (D2); `timeout` injected through
      the seam with the heartbeat still there afterwards (D6).
- [x] T007 `tests/test_cli_disconnect.py`: idempotence (D10), the byte-identical credential across
      every outcome (D7), D3's heartbeat rewritten between the signal and the check, and the whole
      module under a `urlopen` that raises (D9).

## Phase 3: The command

- [x] T008 `keel_runtime/cli.py`: the `disconnect` subparser with `--home` and `--base-url`, and
      `_run_disconnect` — one `print`, one `return 0` (FR-001, FR-005).
- [x] T009 `keel_runtime/cli.py`: `_address_keys`, factored out of `_environment_keys` so one place
      decides the address, and used by both `status` and `disconnect` (FR-008).
- [x] T010 `tests/test_cli_disconnect.py`: the CLI as a real subprocess — exactly one JSON line and
      exit 0 for `not_running`, `stale_pid_cleared` and a real `stopped`; the address keys in every
      shape; and `--home`/`KEEL_HOME`/`--base-url` resolving the **identical** home `status`
      resolves from the same inputs (FR-001, FR-008, FR-013).

## Phase 4: The seam

- [x] T011 `keel_runtime/cli.py`: `_say_goodbye(client, state, config)` and its call site after
      `run_loop` returns — G6's branch first, a client without the method a no-op, every
      `Exception` swallowed, `KeyboardInterrupt` at the call site swallowed too (FR-010).
- [x] T012 `keel_runtime/poller.py`: `run_loop` returns the `RuntimeState` it finished with, and
      `_run_connect` uses it (FR-011).
- [x] T013 `tests/test_shutdown_goodbye.py`: today's no-op with a real `CloudClient` and no network
      (FR-010); a stub client called once with the right session id and token; the ordering against
      the heartbeat's removal (G3); a client that raises, times out or 404s changing neither the
      exit code nor anything else (G1); no call at all with no agent session (G6); and the
      re-authorized session being the one addressed (FR-011).

## Phase 5: The prose and the gate

- [x] T014 `README.md`: the way out beside the way in — the four outcomes, the two bounds, exit 0,
      idempotence, the untouched credential, and a pointer to the contract file.
- [x] T015 Gate green on 3.9 and on the newest interpreter present (SC-001, SC-002); commits in the
      house style with the trailers; merge to `master` and push (the founder asked for it tonight).

## Discovered while doing it

- **`run_loop` rebinds `state`** (T012, and now FR-011). Placing the goodbye seam turned up that
  `_reauthorize` replaces the `RuntimeState` *inside* the loop when a credential expires mid-run,
  so `_run_connect`'s own local can name an agent session that is already dead. Left alone, the
  second pass's first bug would have been a goodbye addressed to the wrong session — reproducible
  only by expiring a credential mid-run. `run_loop` now returns the state it finished with; one
  `return`, and a test that drives it.
- **A zombie reads as alive.** `heartbeat.pid_alive` is `os.kill(pid, 0)`, which succeeds for a
  process that has exited but not been reaped — so a test whose child is its *own* child would
  watch that child survive `SIGTERM`, wait out the grace, and report `SIGKILL`. Every child in
  `tests/test_cli_disconnect.py` is reaped by a thread of the test process. This is a test-bed
  fact, not a runtime one: the runtime signals a process it did not start and never becomes its
  parent.
- **The seam looks for a method rather than being empty** (T011). An empty `_say_goodbye` would be
  untestable beyond "it was called", and G3's ordering would have been discovered later, next to a
  live network call. Looking for `end_agent_session` on the client makes today's no-op assertable
  from both ends *and* makes the second pass a one-method change to `cloud_client.py` with no edit
  to the call site.
- **`--base-url` was worth accepting** (FR-001), though the design's §3 signature names only
  `--home`. Since spec 004 the home follows the address, so a caller that knows which Keel it means
  would otherwise have to compute a host slug to say which home it means. It never reaches the
  network.
- **Two outcomes the design does not name, folded into ones it does.** A `ProcessLookupError` from
  the signal itself (the process left between the liveness check and the signal) is `stopped`; a
  `PermissionError` (a pid this user may not signal) is `timeout`, with the heartbeat left in
  place. Both are in the contract's prose and both have a test; neither adds an outcome.
- **229 tests before, 257 after.** Green on 3.9.6 and 3.13.13, with neither `keyring` nor
  `jsonschema` installed. No existing test needed an edit (SC-005).

## Open items (not this spec's)

- **The goodbye's call** — §10 step 4. `_say_goodbye` finds no `end_agent_session` on today's
  `CloudClient` and returns having done nothing. The second pass adds that one method — `POST
  /v2/agent-sessions/{id}/disconnect`, `{}`, `204`, a 2s timeout, no retry, every exception
  swallowed including the `404` an older Keel Cloud gives it — and **this call site does not
  change**. It is blocked on keel-cloud spec `033-agent-session-goodbye` (step 3) existing to be
  called.

  **Landed, second pass (2026-09-09), on `033` having shipped**: `CloudClient.end_agent_session`
  in `keel_runtime/cloud_client.py`, exactly as specified above, and *no edit* to `_say_goodbye`
  or its call site — the `getattr` lookup this pass's own tasks.md predicted starts working with
  the client alone. `tests/test_cloud_client_goodbye.py` (new) proves the wire call itself against
  a real, local `http.server` — the right path, bearer and body; `404`/`403` as `ApiError`; a
  hanging server bounded by the caller's own timeout, not the server's pace; connection-refused as
  `NetworkError`. Found doing it: on Python 3.9 a timeout **reading** a response (as opposed to
  connecting) raises bare `socket.timeout`, which is not `TimeoutError` there (they are the same
  class from 3.10 on) and reached neither of `_request`'s two exception clauses — so `cloud_client.
  py`'s catch-all is now `except (socket.timeout, TimeoutError)`, the one-clause fix that makes the
  hang test pass identically on both floors. `tests/test_shutdown_goodbye.py`'s two tests that
  asserted "today's client has no goodbye" are updated to assert the opposite, since it now does.
- **A `RUNNING` job whose runtime went away** stays `RUNNING` forever, and its interaction stays
  `PENDING` forever (§6e). That is true today, of a crash and a closed laptop alike; disconnect
  makes it routine without creating it. The fix is the goodbye's second effect and belongs to
  keel-cloud's step 3, with the crash case still open behind it as a defect against spec 020.
- **Pid reuse** (§6c, decision 11) — accepted and unmitigated. The named mitigation, if it is ever
  wanted, is to record the process's own start time in the heartbeat and compare it before
  signalling. Not built, because nobody has hit it.
- **keel-e2e-eval's `stack/runtime.py::kill`** still hand-rolls this command's three steps, with a
  docstring that is a specification of it. §8.4 turns it into a caller; that is step 6.
