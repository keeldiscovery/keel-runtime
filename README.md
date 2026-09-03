# keel-runtime

The local runtime half of Keel Connect (spec `020-keel-connect`): a small Python
package that authorizes a device against Keel Cloud, keeps one agent session alive,
long-polls for inference jobs, executes them, and reports the answer back.

The runtime owns no workflow, project, instruction, memory, or schema state — it is a
stateless executor of whatever `request_payload` Cloud queues for it.

## Running it

Uninstalled, straight from this directory (this is how the E2E test launches it, and it
works with nothing but a stock `python3` — see "Dependencies" below):

```sh
cd keel-runtime
python3 -m keel_runtime connect --base-url http://localhost:8080
```

Installed (`pip install -e .`), the same command is available as:

```sh
keel connect --base-url http://localhost:8080
```

Press Ctrl+C to stop; the runtime exits cleanly.

## Checking whether a runtime is already connected

`connect` maintains a small heartbeat file under `$KEEL_HOME` (`runtime.heartbeat.json`,
sibling of `credentials.json`/`config.json`) while it runs -- written once the agent
session exists and refreshed after every poll cycle, removed on clean shutdown
(Ctrl+C/`SIGTERM`). A separate `status` subcommand reads it, without ever making a
network call, and prints a single line of JSON:

```sh
python3 -m keel_runtime status
# {"running": false}
# or, with a live runtime:
# {"running": true, "pid": 41213, "agent_session_id": "...", "base_url": "...",
#  "last_heartbeat_at": "...", "connected": true}
```

This exists so something outside the runtime process (in practice: a Claude Code skill
in another repository, deciding whether to launch `keel connect`) can check liveness
cheaply and offline instead of parsing process lists. `status` always exits 0 -- "not
running" is a normal answer, not an error. Its exact output shapes and guarantees are
the stable contract at
[`specs/021-keel-runtime-status/contracts/status-cli-output.md`](../specs/021-keel-runtime-status/contracts/status-cli-output.md);
the heartbeat file's own schema is an implementation detail, not part of that contract.

`--home` (same `KEEL_HOME`-resolution precedence as `connect`) is the only flag
`status` accepts.

### `connect` flags

| Flag | Meaning |
|---|---|
| `--base-url` | Keel Cloud base URL (e.g. `http://localhost:8080`) |
| `--executor` | which `Executor` to run jobs with: `claude-code` (default) or `stub` (test-only, never a default) |
| `--home` | overrides `KEEL_HOME` for this run |
| `--credential-backend` | `auto` (default), `file`, or `keyring` |
| `--no-browser` | do not open a browser during device authorization; print the URL instead |
| `--log-level` | log verbosity (informational only in this pass) |

## Configuration precedence

For each key, the first source that sets it wins: **CLI flag > environment variable >
`$KEEL_HOME/config.json`**.

| Key | Flag | Env var | Config file key |
|---|---|---|---|
| Base URL | `--base-url` | `KEEL_BASE_URL` | `base_url` |
| Executor | `--executor` | `KEEL_EXECUTOR` | `executor` |
| Home directory | `--home` | `KEEL_HOME` | — |
| Credential backend | `--credential-backend` | `KEEL_CREDENTIAL_BACKEND` | `credential_backend` |
| Heartbeat staleness threshold (seconds) | — | `KEEL_HEARTBEAT_STALE_AFTER` | `heartbeat_stale_after` |

`KEEL_HOME` defaults to `~/.keel` if nothing sets it. A missing `base_url` after all
three sources are checked exits with a one-line remedy rather than a traceback.

`heartbeat_stale_after` controls how long `status` will still report `running: true`
for a live-but-unrefreshed heartbeat before treating it as dead (env or
`$KEEL_HOME/config.json` only -- neither `connect` nor `status` expose a flag for it).
It defaults to one full long-poll cycle's worst case plus slack (50s with `connect`'s
own defaults) so a runtime merely waiting on a slow long-poll is never mistaken for
dead; see `specs/021-keel-runtime-status/research.md` §4.

## Executors

- **`claude-code`** (default) — the real executor. Invokes the `claude` CLI in
  non-interactive print mode (`claude -p`), rendering the job's request into a
  SYSTEM/CONTEXT/HISTORY/INPUT/RESPONSE-REQUIREMENTS prompt and parsing the first JSON
  object out of its stdout.
- **`stub`** — deterministic, test-only. Selected with `--executor stub`, never a
  default. Driven entirely by `request_payload.input.content`: see
  `keel_runtime/testing/stub_executor.py`. This is what `KeelConnectJourneyTest`
  (spec SC-002) drives directly.

## Dependencies

The runtime's core runs on the Python standard library alone (`urllib.request`,
`json`, `subprocess`, `dataclasses`, `webbrowser`, `argparse`) — the same posture as
the served bridge script. Two optional accelerators are used only when importable,
never required:

- `keyring` — used by `credential_store.py` for OS-native secret storage when the
  credential backend is not explicitly `file`; otherwise credentials are written to a
  `0600` JSON file at `$KEEL_HOME/credentials.json`.
- `jsonschema` — used by `response_validator.py` for full JSON-Schema validation of a
  completed job's result; otherwise a small subset validator mirrors the server's own
  `ResultSchemaValidator` (spec FR-019).

## Tests

```sh
python3 -m unittest discover -s tests -t .
```

wired into the Java build's `check` task as `keelRuntimeTest` (spec SC-001).
