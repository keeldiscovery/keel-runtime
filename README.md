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
| `--executor` | which `Executor` to run jobs with: `claude-code` (default), `stub`, or `scripted` (test-only, never a default) |
| `--script` | path to a scripted-executor script (only meaningful with `--executor scripted`; ignored with a warning otherwise) |
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
| Script path (`scripted` executor only) | `--script` | `KEEL_SCRIPT` | `script` |
| Heartbeat staleness threshold (seconds) | — | `KEEL_HEARTBEAT_STALE_AFTER` | `heartbeat_stale_after` |
| Per-job budget, USD (`claude-code` executor only) | — | `KEEL_JOB_BUDGET_USD` | `budget_usd` |
| Per-job max turns (`claude-code` executor only) | — | `KEEL_JOB_MAX_TURNS` | `max_turns` |

`KEEL_HOME` defaults to `~/.keel` if nothing sets it. A missing `base_url` after all
three sources are checked exits with a one-line remedy rather than a traceback.

`heartbeat_stale_after` controls how long `status` will still report `running: true`
for a live-but-unrefreshed heartbeat before treating it as dead (env or
`$KEEL_HOME/config.json` only -- neither `connect` nor `status` expose a flag for it).
It defaults to one full long-poll cycle's worst case plus slack (50s with `connect`'s
own defaults) so a runtime merely waiting on a slow long-poll is never mistaken for
dead; see `specs/021-keel-runtime-status/research.md` §4.

## Executors

- **`claude-code`** (default) — the real executor. Invokes the `claude` CLI in a
  closed, tool-less, session-less shape (spec `002-words-are-words`; design of record
  keel-cloud `canon/designs/words-are-words-design.md` §L1) so that text a stranger or
  the founder typed can be read as source material but never followed as an
  instruction:

  ```
  claude -p
    --tools ""                      # no built-in tools at all
    --strict-mcp-config             # no MCP servers from any config
    --setting-sources ""            # ignore user, project and local settings (CLAUDE.md included)
    --no-session-persistence        # nothing written to disk for later resumption
    --max-turns <N>                 # KEEL_JOB_MAX_TURNS, default 2
    --max-budget-usd <amount>       # KEEL_JOB_BUDGET_USD, default 0.25
    --output-format json            # the envelope, not raw prose
    --json-schema <contract>        # the job's own response contract, enforced by the CLI
    --system-prompt <fixed text>    # runtime-owned, identical for every job
  ```

  with the prompt on **stdin** (never argv), `cwd` an empty per-job directory under
  `$KEEL_HOME/jobs/<job_id>/`, and an allow-listed environment (`PATH`, `HOME`, `USER`,
  `LANG`, `LC_*`, `TMPDIR`, `TERM`, plus any `ANTHROPIC_*`/`CLAUDE_*` variable the CLI
  needs for its own auth — never `KEEL_HOME`, never `KEEL_BASE_URL`). `--bare` is
  deliberately **not** used: it skips keychain reads and the CLI reports "Not logged
  in". The result comes from the CLI's own JSON envelope's `structured_output`, never
  scraped from stdout. **Requires Claude Code ≥ 2.1.259.** An older CLI without
  `--json-schema` exits non-zero and the job fails `LLM_UNAVAILABLE`.

  Every human- or model-authored string in the prompt — the founder's framing text, a
  participant's answers, earlier turns — sits inside one `<<<KEEL-DATA <nonce>>> ...
  <<<END KEEL-DATA <nonce>>>` fence with a fresh per-job random nonce, under a heading
  that says it is source material, not an instruction; the fixed system prompt states
  the same rule.

  The per-job directory (`$KEEL_HOME/jobs/<job_id>/`) holds `envelope.json` (the CLI's
  own JSON envelope, verbatim) and `request.json` (the prompt sections that were sent)
  once the job finishes, success or failure — diagnostic logs, kept across jobs but
  pruned to the newest 50 each time `connect` starts.

- **`stub`** — deterministic, test-only. Selected with `--executor stub`, never a
  default. Driven entirely by `request_payload.input.content`: see
  `keel_runtime/testing/stub_executor.py`. This is what `KeelConnectJourneyTest`
  (spec SC-002) drives directly.
- **`scripted`** — deterministic, test-only. Selected with `--executor scripted`, never
  a default. See "Running deterministically" below.

## Running deterministically

`--executor scripted [--script PATH]` answers every inference job from a **script**: a
JSON file of results keyed by screen (`PROBLEM_FRAME`, `PROBLEM_ASSUMPTIONS`,
`SOLUTION_FRAME`, `SOLUTION_ASSUMPTIONS`, `COMMERCIAL_FRAME`, `COMMERCIAL_ASSUMPTIONS`,
`SOLUTION_REFRAME`, `COMMERCIAL_REFRAME`, `INTERPRET`, `BRIEF`), each a list of entries
consumed in order (the last entry repeats once the list is exhausted). The screen is
never LLM-derived — it is inferred from the request payload's own `context` keys, per
keel-cloud spec `022-inference-orchestrator` FR-010, so the same poll loop, the same
`response_validator`, and the same `complete`/`fail` calls run exactly as they do with
any other executor.

`--script` is only meaningful with `--executor scripted`; given with any other
executor it is ignored with a warning. It falls back to `KEEL_SCRIPT`, then to the
bundled default, `keel_runtime/testing/scripts/payroll-exceptions.json` — the
payroll-exceptions discovery drawn in keel-cloud's `canon/mockups/`. This is what
keel-e2e-eval's connect-stack spec (`005-connect-stack`) drives to run a whole
discovery end to end without an LLM. See
[`specs/001-scripted-executor/spec.md`](../specs/001-scripted-executor/spec.md).

## Dependencies

The runtime's core runs on the Python standard library alone (`urllib.request`,
`json`, `subprocess`, `dataclasses`, `webbrowser`, `argparse`) — no third-party
package is needed to connect. Two optional accelerators are used only when importable,
never required:

- `keyring` — used by `credential_store.py` for OS-native secret storage when the
  credential backend is not explicitly `file`; otherwise credentials are written to a
  `0600` JSON file at `$KEEL_HOME/credentials.json`.
- `jsonschema` — used by `response_validator.py` for full JSON-Schema validation of a
  completed job's result; otherwise a small subset validator mirrors the server's own
  `ResultSchemaValidator` (spec FR-019: `type`, `required`, `properties`, `enum`,
  `items`, `additionalProperties: false`; spec `002-words-are-words` FR-006 adds
  `maxLength`, `minLength`, `maxItems`, `pattern`).

## Tests

```sh
python3 -m unittest discover -s tests -t .
```

wired into the Java build's `check` task as `keelRuntimeTest` (spec SC-001).
