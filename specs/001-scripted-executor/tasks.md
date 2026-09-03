# Tasks: The scripted executor

**Input**: [spec.md](spec.md). Stdlib only. `python3 -m pytest tests -q` is the gate.

- [x] T001 `keel_runtime/testing/scripted_executor.py`: `ScriptedExecutor` — load/validate the
      script shape (`{screen: [entries...]}`), infer the screen from `request_payload["context"]`
      keys per spec §Edge Cases, per-screen cursors (last entry repeats), INTERPRET
      `invitationId` fill and heading→id resolution, `ExecutorUnavailable` for unknown key sets,
      missing screens, unresolvable headings.
- [x] T002 `keel_runtime/executor.py`: `get_executor("scripted")` lazy import; the executor needs
      the script path — thread it through `cli.py` (`--script`, `KEEL_SCRIPT`) and wherever
      `get_executor` is called on `connect` (config precedence like the other flags; warn if
      `--script` is given without `--executor scripted`).
- [x] T003 `keel_runtime/testing/scripts/payroll-exceptions.json`: the bundled script per spec
      FR-003 — every screen, the exact statements/beliefs/roles/evidence named there, one
      `NEEDS_INPUT` first on `PROBLEM_FRAME`.
- [x] T004 `tests/fixtures/response_contracts.json`: the ten `completed_result_schema`s copied
      from keel-cloud `specs/022-inference-orchestrator/spec.md` FR-012 (note the source and the
      commit at the top of the file as a JSON comment field `_source`).
- [x] T005 `tests/test_scripted_executor.py`: spec §Acceptance 1–4, the inference table
      exhaustively, exhaustion, refusals, and bundled-script validity against T004 (use
      `jsonschema` if importable, else the runtime's own `response_validator` subset).
- [x] T006 `README.md` "Running deterministically"; `connect --help` shows `--script`.
- [x] T007 Gate: `python3 -m pytest tests -q` green; commit in the house style with the
      trailers; no push.
