# Feature Specification: The heartbeat says who launched it, and whether it is busy

**Feature Branch**: `007-launcher-version`

**Created**: 2026-09-11

**Status**: Implemented

**Input**: the founder, 2026-09-11 — *"whenever a user types keel connect the old runtime should be
killed and the new one should start … even if the other runtime may have started in another CLI
session"* — settled with one guard: a running runtime is replaced only when the bundle is newer
and the runtime is idle. Design of record: keel-cloud `canon/designs/upgrade-in-place-design.md`.
This spec is the runtime's half; keel-connect-skill spec `005-upgrade-in-place` is the other.

## Scope

- **FR-001** `connect` accepts `--launcher-version <semver>` (environment form
  `KEEL_LAUNCHER_VERSION`). The value is recorded, never interpreted, and is `None` when absent.
- **FR-002** Every heartbeat this process writes — the awaiting-approval record, the first
  connected write, and every poll-cycle write — carries `launcher_version`.
- **FR-003** The heartbeat carries `job_id` from the moment a job is delivered until the write
  after `_handle_job` returns, and `null` otherwise. Nothing else about the poll loop changes.
- **FR-004** `status`'s running shape reports `launcher_version` (may be `null`) and `busy`
  (`job_id is not null`). The contract in keel-cloud `specs/021-keel-runtime-status/contracts/
  status-cli-output.md` is amended the same day. Not-running shapes are unchanged.
- **FR-005** A heartbeat written before this spec — no such keys — reads back as unknown launcher,
  idle. No compatibility shim beyond that: nothing else reads the file.
- **FR-006** `keel_runtime.__version__` is `0.2.0`.

## Tests

`tests/test_heartbeat.py` (round trip and the pre-spec file), `tests/test_cli_status.py` (the
running shape, the flag, the environment name), `tests/test_poller.py` (the job named while it
runs and cleared after), `tests/test_awaiting_approval.py` (the running-not-connected shape).
