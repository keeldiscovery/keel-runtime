# Implementation Plan: The way out — `keel disconnect`

**Branch**: `003-keel-disconnect` | **Date**: 2026-09-08 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md) (FR-001..013, SC-001..005) and the design of record, keel-cloud
`canon/designs/keel-disconnect-design.md` §3, §4.2, §6, §7, §8.1, §9, §10 step 2; the derived home
of `canon/designs/keel-skill-design.md` §6.3 as this repository's spec `004-shipped-runtime` built
it.

## Summary

One new module, one new subcommand, one new contract, one seam, and one `return`. `disconnect`
reads the heartbeat this home already keeps, sends the signal the runtime's own shutdown handler
already honours, waits within a bound, **proves** the pid is gone, escalates once, removes the
heartbeat only while it still names the pid that was signalled, and prints one line of JSON with
one of four outcomes. It makes no network call, touches no credential and keeps no state between
runs. Beside it, `_run_connect` gains the place the goodbye will go — after the stack has unwound,
never in the signal handler — as a no-op that the second pass fills in without editing this call
site.

Nothing else in the runtime moves: the poller, both test executors, the wire shapes and the zero
required dependencies are untouched.

## Technical Context

**Language/Version**: Python **3.9** (floor) through 3.13, as spec 004 fixed it.

**Primary Dependencies**: none. `os.kill`, `signal`, `time.monotonic` and the existing
`heartbeat` module are the whole toolkit.

**Storage**: one file, `$KEEL_HOME/runtime.heartbeat.json` — read, and sometimes unlinked. Nothing
else in the home is opened.

**Testing**: `unittest` modules under `tests/`, run with `python -m pytest`. 229 tests before this
feature.

**Target Platform**: macOS, Linux and Windows. On Windows `os.kill` terminates unconditionally
rather than delivering a catchable signal, so the escalation is unreachable there in practice and
the one test that needs a process to *ignore* `SIGTERM` skips itself.

**Project Type**: single Python package with a CLI (`keel`, `python3 -m keel_runtime`).

**Constraints**: standard library only; one line of JSON on stdout; exit 0, always; no network
call; 15 seconds worst case.

**Scale/Scope**: ~110 lines of new runtime source, two new test modules.

## Constitution Check

This repository has no constitution file. The rules it is held to are the design's invariants, and
each is cited by id in the code comment, the spec requirement and the test that checks it.

| Invariant | How this plan satisfies it |
|---|---|
| **D1** four unreadable cases are one `not_running` | `heartbeat.read` already collapses them and returns `None`; disconnect adds no second reading |
| **D2** a dead pid is removed, never signalled | step 2 returns before any `kill`, asserted with a recording fake `kill` |
| **D3** the heartbeat is removed only while it names the signalled pid | `_remove_if_still_ours` re-reads before unlinking |
| **D4** no `/complete`, no `/fail` | disconnect has no client, no token and no wire vocabulary at all |
| **D5** `SIGTERM` then `SIGKILL`, in that order, bounded | one function, one direction, two constants |
| **D6** on `timeout` the heartbeat stays | the only path that returns without calling `_remove_if_still_ours` |
| **D7** the credential is never touched | disconnect never constructs a `CredentialStore`; a byte-comparison test per outcome |
| **D8** one JSON line, exit 0 | `_run_disconnect` has exactly one `print` and one `return 0` |
| **D9** no network call | the module imports nothing that can reach a socket; the test module runs under a `urlopen` that raises |
| **D10** idempotent | there is no state to keep: the answer is a function of the heartbeat file |
| **G1** a failed goodbye changes nothing | the seam swallows `Exception`, and its call site swallows `KeyboardInterrupt` |
| **G3** goodbye after the heartbeat is gone | it is called after `run_loop` returns, and the handler removes the file before raising |
| **G6** never when there is no agent session | the seam's first branch |

## Project Structure

### Documentation (this feature)

```text
specs/003-keel-disconnect/
├── spec.md                                # what lands and why
├── plan.md                                # this file
├── tasks.md                               # the ordered list, ticked as it went, with Discovered
└── contracts/
    └── disconnect-cli-output.md           # the stable, external contract (FR-012)
```

No `research.md` or `data-model.md`: the research is the design of record and is cited section by
section, and the only entity is a file this repository already owns. Unlike spec 004, this feature
**does** carry a `contracts/` directory, because the contract it creates is its own — keel-cloud
owns `status`'s, and keel-connect-skill will own the script's.

### Source Code (repository root)

```text
keel_runtime/
├── disconnect.py          new: the flow, its two bounds and its seam   (FR-002, FR-003, FR-009)
├── cli.py                 the subcommand, the address keys,
│                          the goodbye seam and its call site           (FR-001, FR-008, FR-010)
├── poller.py              one line: `run_loop` returns its state       (FR-011)
└── (everything else unchanged)

tests/
├── test_cli_disconnect.py     new: every outcome, real children, the seam's fakes, D3, D7,
│                              D9, D10, --home parity with status
├── test_shutdown_goodbye.py   new: G1, G3, G6 and today's no-op
└── (everything else unchanged)

README.md                      the way out, beside the way in
```

**Structure Decision**: the flow lives in its own module rather than in `cli.py`. `cli.py` is
already the place every subcommand's *wiring* lives, and disconnect's wiring is four lines; what is
new here is a small algorithm with four exits, two bounds and four injected collaborators, and it
is the algorithm the tests drive. Keeping it out of `cli.py` also keeps the seam's signature — the
thing §8.1 specifies by name — importable without importing the CLI.

## Phasing

1. **The spec, the plan and the contract.** The contract first, because it is what two other
   repositories will be written against, and writing it first is what makes the shapes settle
   before the code does.
2. **The flow** (FR-002, FR-003, FR-004, FR-009) — `disconnect.py` and its unit tests, driven
   entirely through the seam with fakes plus two real child processes. Useful alone as a library.
3. **The command** (FR-001, FR-005, FR-006, FR-007, FR-008) — the subparser, the address keys, the
   one `print`, and the subprocess-level tests that hold the contract.
4. **The seam** (FR-010, FR-011) — `_say_goodbye`, its call site, `run_loop`'s `return`, and
   `test_shutdown_goodbye.py`. Depends on nothing above and is the only part that anticipates
   another repository.
5. **The prose and the gate** — README, and the suite green on 3.9 and on the newest interpreter
   present.

## Complexity Tracking

| Decision | Why needed | Simpler alternative rejected because |
|---|---|---|
| **Four injected collaborators** (`kill`, `alive`, `clock`, `sleep`) on `disconnect` | two of the four outcomes cannot be produced by a real process on demand — nothing survives `SIGKILL` to order — and the escalation path would otherwise cost ten real seconds per run | `unittest.mock.patch` of module globals would test the same lines while hiding the fact that the bounds are the caller's to choose; the design names this signature (§8.1) |
| **`_remove_if_still_ours` re-reads the file** instead of unlinking what it read at step 1 | between the signal and the check, the runtime's own handler removes the file, and something else may have written a new one — unlinking blind would delete a live runtime's heartbeat (D3) | "unlink if the path exists" is one syscall shorter and deletes the wrong process's record on the one day it matters |
| **`base_url`/`environment` from the heartbeat when it is readable** | it names the Keel the process that was just stopped was talking to | resolving afresh would let `disconnect` say it stopped a runtime on a Keel that runtime was not connected to |
| **The goodbye seam looks for a method on the client** rather than being an empty function | it makes the no-op *testable today* — a stub client with the method proves the ordering, the swallowing and the G6 branch now, so the second pass adds a client method and nothing else | an empty `def _say_goodbye(): pass` is untestable beyond "it was called", and would leave G3's ordering to be discovered later, next to a live network call |
| **`run_loop` returns its state** (FR-011) | `_reauthorize` rebinds `state` inside the loop, so the caller's local can name a dead agent session | leaving it would make the second pass's first bug a goodbye addressed to the wrong session, found only after a credential expiry — the rarest reproduction there is |
