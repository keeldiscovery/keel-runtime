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

- [ ] T001 `specs/003-keel-disconnect/contracts/disconnect-cli-output.md`: the four shapes, the
      three address keys, the invocation and the nine guarantees, in the five-part shape
      keel-cloud's `status-cli-output.md` uses (FR-012).
- [ ] T002 `spec.md` and `plan.md`: the five user stories, FR-001..013, the invariant table, and
      what is out of scope by name.

## Phase 2: The flow

- [ ] T003 `keel_runtime/disconnect.py`: `disconnect(home, *, grace, kill_after, kill, alive,
      clock, sleep)` — the design's §3.1 steps in order, the four outcomes, `_remove_if_still_ours`
      (D3), the heartbeat left in place on `timeout` (D6) (FR-002, FR-003, FR-009).
- [ ] T004 `tests/test_cli_disconnect.py`: `stopped`/`SIGTERM` against a real child that takes the
      default disposition, and against one that installs the runtime's own handler shape and
      removes its heartbeat on the way out (FR-013).
- [ ] T005 `tests/test_cli_disconnect.py`: `stopped`/`SIGKILL` against a real child that installs
      `signal.SIG_IGN` for `SIGTERM`, with a shortened grace so the test is fast; `waited_ms >=`
      the grace (D5).
- [ ] T006 `tests/test_cli_disconnect.py`: `not_running` for an empty home, a malformed heartbeat
      and one short a required field — all three identical (D1); `stale_pid_cleared` with a
      recording fake `kill` asserting **nothing was signalled** (D2); `timeout` injected through
      the seam with the heartbeat still there afterwards (D6).
- [ ] T007 `tests/test_cli_disconnect.py`: idempotence (D10), the byte-identical credential across
      every outcome (D7), D3's heartbeat rewritten between the signal and the check, and the whole
      module under a `urlopen` that raises (D9).

## Phase 3: The command

- [ ] T008 `keel_runtime/cli.py`: the `disconnect` subparser with `--home` and `--base-url`, and
      `_run_disconnect` — one `print`, one `return 0` (FR-001, FR-005).
- [ ] T009 `keel_runtime/cli.py`: `_address_keys`, factored out of `_environment_keys` so one place
      decides the address, and used by both `status` and `disconnect` (FR-008).
- [ ] T010 `tests/test_cli_disconnect.py`: the CLI as a real subprocess — exactly one JSON line and
      exit 0 for `not_running`, `stale_pid_cleared` and a real `stopped`; the address keys in every
      shape; and `--home`/`KEEL_HOME`/`--base-url` resolving the **identical** home `status`
      resolves from the same inputs (FR-001, FR-008, FR-013).

## Phase 4: The seam

- [ ] T011 `keel_runtime/cli.py`: `_say_goodbye(client, state, config)` and its call site after
      `run_loop` returns — G6's branch first, a client without the method a no-op, every
      `Exception` swallowed, `KeyboardInterrupt` at the call site swallowed too (FR-010).
- [ ] T012 `keel_runtime/poller.py`: `run_loop` returns the `RuntimeState` it finished with, and
      `_run_connect` uses it (FR-011).
- [ ] T013 `tests/test_shutdown_goodbye.py`: today's no-op with a real `CloudClient` and no network
      (FR-010); a stub client called once with the right session id and token; the ordering against
      the heartbeat's removal (G3); a client that raises, times out or 404s changing neither the
      exit code nor anything else (G1); no call at all with no agent session (G6); and the
      re-authorized session being the one addressed (FR-011).

## Phase 5: The prose and the gate

- [ ] T014 `README.md`: the way out beside the way in — the four outcomes, the two bounds, exit 0,
      idempotence, the untouched credential, and a pointer to the contract file.
- [ ] T015 Gate green on 3.9 and on the newest interpreter present (SC-001, SC-002); commits in the
      house style with the trailers; merge to `master` and push (the founder asked for it tonight).

## Open items (not this spec's)

- **The goodbye's call** — §10 step 4. `_say_goodbye` finds no `end_agent_session` on today's
  `CloudClient` and returns having done nothing. The second pass adds that one method — `POST
  /v2/agent-sessions/{id}/disconnect`, `{}`, `204`, a 2s timeout, no retry, every exception
  swallowed including the `404` an older Keel Cloud gives it — and **this call site does not
  change**. It is blocked on keel-cloud spec `033-agent-session-goodbye` (step 3) existing to be
  called.
- **A `RUNNING` job whose runtime went away** stays `RUNNING` forever, and its interaction stays
  `PENDING` forever (§6e). That is true today, of a crash and a closed laptop alike; disconnect
  makes it routine without creating it. The fix is the goodbye's second effect and belongs to
  keel-cloud's step 3, with the crash case still open behind it as a defect against spec 020.
- **Pid reuse** (§6c, decision 11) — accepted and unmitigated. The named mitigation, if it is ever
  wanted, is to record the process's own start time in the heartbeat and compare it before
  signalling. Not built, because nobody has hit it.
- **keel-e2e-eval's `stack/runtime.py::kill`** still hand-rolls this command's three steps, with a
  docstring that is a specification of it. §8.4 turns it into a caller; that is step 6.
