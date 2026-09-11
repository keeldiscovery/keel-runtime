# keel-runtime

The local runtime half of Keel Connect (spec `020-keel-connect`): a small Python
package that authorizes a device against Keel Cloud, keeps one agent session alive,
long-polls for inference jobs, executes them, and reports the answer back.

The runtime owns no workflow, project, instruction, memory, or schema state — it is a
stateless executor of whatever `request_payload` Cloud queues for it.

**Python 3.9 or newer is the only thing it needs.** It ships *inside* Keel's skill (design of
record: keel-cloud `canon/designs/keel-skill-design.md`, spec
[`004-shipped-runtime`](specs/004-shipped-runtime/spec.md)), so it is run by whatever interpreter
ran the skill's own script — on a Mac with the Xcode command-line tools that is `/usr/bin/python3`
at 3.9.6, which is why 3.9 is the floor. `.github/workflows/tests.yml` runs the whole suite on
3.9–3.13 and **installs neither `keyring` nor `jsonschema`**, because the shipped behaviour is the
one without them and that is the configuration worth testing.

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

Press Ctrl+C to stop; the runtime exits cleanly. From anywhere else -- a script, a hook, or
a Claude Code session that has no terminal to press Ctrl+C in -- `keel disconnect` does the
same thing to the runtime this home is running (see "Stopping it again" below).

## Checking whether a runtime is already connected

`connect` maintains a small heartbeat file under `$KEEL_HOME` (`runtime.heartbeat.json`,
sibling of `credentials.json`/`config.json`) while it runs -- written once the agent
session exists and refreshed after every poll cycle, removed on clean shutdown
(Ctrl+C/`SIGTERM`). A separate `status` subcommand reads it, without ever making a
network call, and prints a single line of JSON:

```sh
python3 -m keel_runtime status
# {"running": false, "home": "/Users/you/.keel/localhost-18081",
#  "base_url": "http://localhost:18081", "environment": "localhost:18081",
#  "executor": "claude", "executor_on_path": true}
# or, with a live runtime, the same five keys plus:
# {"running": true, "pid": 41213, "agent_session_id": "...", "last_heartbeat_at": "...",
#  "connected": true, ...}
```

`home`, `environment`, `executor` and `executor_on_path` are present in **both** shapes, and
`base_url` is always present (spec `004-shipped-runtime` FR-009). `environment` is *which Keel*:
`"cloud"` for the built-in default, `host:port` for anything else, `null` when nothing names a Keel
at all. In the running shape the address is the one the **live process** connected to (the
heartbeat's own record), not what a fresh resolution would pick now. `executor_on_path` is whether
that executor's CLI is on `PATH`; `scripted` and `stub` run in this process and are always
available, and `executor` is what the **selection order** resolved (below), not merely the first
thing that named one -- so `keel status` and `connect`'s own `KEEL_EXECUTOR=` line can never
disagree. There is no `claude_on_path` key and there never will be: it would read `false` on a
healthy Copilot-hosted runtime, which is a lie about health.

This exists so something outside the runtime process (in practice: a Claude Code skill
in another repository, deciding whether to launch `keel connect`) can check liveness
cheaply and offline instead of parsing process lists. `status` always exits 0 -- "not
running" is a normal answer, not an error. Its exact output shapes and guarantees are
the stable contract at
[`specs/021-keel-runtime-status/contracts/status-cli-output.md`](../specs/021-keel-runtime-status/contracts/status-cli-output.md);
the heartbeat file's own schema is an implementation detail, not part of that contract.

`--home` (same `KEEL_HOME`-resolution precedence as `connect`) is the only flag
`status` accepts.

## Stopping it again

`disconnect` is the way out, said the same way as the way in (spec `003-keel-disconnect`). It finds
the runtime **this home** is running from the same heartbeat file, sends the `SIGTERM` that
process's own shutdown handler already honours -- so it is indistinguishable, to the runtime, from
the founder pressing Ctrl+C -- waits, **checks that the pid is gone**, and says what happened in
one line of JSON:

```sh
python3 -m keel_runtime disconnect
# {"outcome": "stopped", "pid": 41213, "waited_ms": 84, "signal": "SIGTERM",
#  "home": "/Users/you/.keel/localhost-18081", "base_url": "http://localhost:18081",
#  "environment": "localhost:18081"}
```

Four outcomes, and `outcome` is the whole answer: `stopped` (it was alive, it was signalled, it is
gone), `not_running` (no readable heartbeat for this home), `stale_pid_cleared` (a heartbeat left
behind by a runtime that crashed or was killed -- the file is removed and **nothing is signalled**)
and `timeout` (it survived both signals). A runtime that will not take `SIGTERM` inside **10
seconds** is sent `SIGKILL` and given **5 more**; 15 seconds is the worst case. On `timeout` the
heartbeat is deliberately **left in place**, because a process that is still polling must never
read as not running.

Like `status` it exits **0 always** -- "nothing was running" is a normal answer, and so is "it
would not die" -- makes **no network call**, and is idempotent: run it twice and the second run is
`not_running`. It takes `--home` (the same precedence `connect` and `status` use) and `--base-url`,
which names a Keel and therefore, since the home follows the address, names a home.

**It never touches the credential.** Disconnect stops a process; it does not forget a machine, so
saying "keel connect" again reconnects with no device code and no browser. The exact output shapes
and guarantees are the stable contract at
[`specs/003-keel-disconnect/contracts/disconnect-cli-output.md`](specs/003-keel-disconnect/contracts/disconnect-cli-output.md).

A job in flight is **abandoned** -- no `/complete`, no `/fail`, nothing said -- which is exactly
what Ctrl+C does today. Whose problem that job then is stays keel-cloud's own (the in-flight
cancel, `canon/designs/keel-disconnect-design.md` §6e).

On a clean exit -- Ctrl+C, `SIGTERM`, or the `SIGTERM` a `keel disconnect` sends -- the runtime's
very last act, after the heartbeat is already gone, is one bounded, best-effort call that ends its
own agent session (`POST /v2/agent-sessions/{id}/disconnect`, keel-cloud spec
`033-agent-session-goodbye`), so the founder's screen stops saying *Agent connected* within
seconds rather than within ninety. It never delays or changes the exit: a 2s timeout, no retry, and
every failure -- a refused call, a 404 from an older Keel Cloud, a network already gone -- is
swallowed and logged in one line. There is nothing to say goodbye to, and nothing is called, when
the process never got past device authorization.

## Saying which runtime this is

```sh
python3 -m keel_runtime --version    # keel-runtime 0.2.1 (Keel Cloud https://keeldiscovery.com)
python3 -m keel_runtime --license    # the SPDX id, the copyright line and the full text's URL
```

Neither needs a subcommand and both exit 0. `keel_runtime.__version__` is the single source of
truth — the shipped runtime is run from a directory on `PYTHONPATH` and never installed, so package
metadata would not answer — and a test asserts `pyproject.toml` agrees with it. `--version` names
`CLOUD_BASE_URL` whenever that constant has a value, which it does as of design §13 step 8.

### `connect` flags

| Flag | Meaning |
|---|---|
| `--base-url` | Keel Cloud base URL (e.g. `http://localhost:8080`) |
| `--executor` | which `Executor` to run jobs with: `claude` (default; `claude-code` is a permanent alias), `copilot`, or `stub`/`scripted` (test-only, never a default). Named explicitly it wins outright -- **even if its CLI is missing**, which is reported per job rather than second-guessed here |
| `--host` | the host this runtime was launched under: `claude`, `copilot`, or `auto` (default). The skill passes it; `auto` reads the environment's own host markers instead |
| `--copilot-model` | the `--model` slug to pin the `copilot` executor to; unpinned by default |
| `--script` | path to a scripted-executor script (only meaningful with `--executor scripted`; ignored with a warning otherwise) |
| `--context-keys` | path to keel-cloud's exported `context-keys.json`, the scripted executor's screen-inference table (same rule: `scripted` only, ignored with a warning otherwise) |
| `--home` | overrides `KEEL_HOME` for this run |
| `--credential-backend` | `auto` (default), `file`, or `keyring` |
| `--no-browser` | do not open a browser during device authorization; print the URL instead |
| `--log-level` | log verbosity (informational only in this pass) |

`connect`'s **first line of output** names the Keel it is talking to, in the same machine-readable
family as the two device-authorization lines a harness already parses:

```
KEEL_ENVIRONMENT=localhost:18081 base_url=http://localhost:18081
KEEL_EXECUTOR=claude source=ambiguous-path binary=/Users/you/.local/bin/claude version=2.1.263 (Claude Code)  # both CLIs on PATH; pass --executor to choose
KEEL_USER_CODE=WDJB-MJHT
KEEL_VERIFICATION_URI=http://localhost:5173/connect?code=WDJB-MJHT
```

## Configuration precedence

For each key, the first source that sets it wins: **CLI flag > environment variable >
`$KEEL_HOME/config.json`**.

| Key | Flag | Env var | Config file key |
|---|---|---|---|
| Base URL | `--base-url` | `KEEL_BASE_URL` | `base_url` — then the built-in `CLOUD_BASE_URL`, below |
| Executor | `--executor` | `KEEL_EXECUTOR` | `executor` |
| Host (a signal, below every explicit executor term) | `--host` | see *Which executor runs* | — |
| Pinned Copilot model (`copilot` executor only) | `--copilot-model` | `KEEL_COPILOT_MODEL` | `copilot_model` |
| Home directory | `--home` | `KEEL_HOME` | — |
| Credential backend | `--credential-backend` | `KEEL_CREDENTIAL_BACKEND` | `credential_backend` |
| Script path (`scripted` executor only) | `--script` | `KEEL_SCRIPT` | `script` |
| Context-keys table (`scripted` executor only) | `--context-keys` | `KEEL_CONTEXT_KEYS` | `context_keys` |
| Heartbeat staleness threshold (seconds) | — | `KEEL_HEARTBEAT_STALE_AFTER` | `heartbeat_stale_after` |
| Per-job budget, USD (`claude` executor only) | — | `KEEL_JOB_BUDGET_USD` | `budget_usd` |
| Per-job max turns (`claude` executor only) | — | `KEEL_JOB_MAX_TURNS` | `max_turns` |
| Per-job wall clock, seconds (both real executors) | — | `KEEL_JOB_TIMEOUT_SECONDS` | `job_timeout_seconds` |

### The home follows the address

`KEEL_HOME` is now an **override, not a requirement**. With neither `--home` nor `KEEL_HOME` set,
the home is `~/.keel/<host-slug>/`, derived from the *resolved* base URL: the host lowercased,
joined to the port with `-` when the URL states one, every character outside `[a-z0-9.-]` replaced
with `-`, no scheme and no path. So `http://localhost:18081` → `~/.keel/localhost-18081/`, and a
runtime pointed at another Keel reads a different directory and finds no credential there (design
§6.3, invariant E-1: two Keels never share one). `bin` is reserved for Keel's own use, so a host
that would slug to it gets `bin-keel` instead.

The resolution is two-phase, because the home decides where the config file is and the config file
may name the base URL:

1. `--home`/`KEEL_HOME` set → that directory, and its `config.json` takes part in the base-URL
   chain as it always has;
2. else a base URL from `--base-url`/`KEEL_BASE_URL`/`CLOUD_BASE_URL` → `~/.keel/<slug>/`, whose
   `config.json` supplies every key **except** `base_url` — a derived home's file may not rename
   the Keel that named it;
3. else nothing resolved → `~/.keel`, whose `config.json` may still name a `base_url`.

### The built-in cloud default

`config.py`'s `CLOUD_BASE_URL` is the **last** term of the base-URL chain, so a fresh install
reaches the real Keel with no configuration at all, and any flag, environment variable or config
file still outranks it. **It is set**, as of design §13 step 8: keel-cloud is deployed at
`https://keeldiscovery.com`, so `keel connect` with nothing else configured reaches that Keel,
`keel status` reports `environment: "cloud"`, and the derived home is
`~/.keel/keeldiscovery.com/`. Only when the constant is cleared back to empty does a missing
`base_url` after every other source is checked exit with a one-line remedy rather than a
traceback — and `keel status` still answers, still exits 0, with `environment: null`, in that case.

`heartbeat_stale_after` controls how long `status` will still report `running: true`
for a live-but-unrefreshed heartbeat before treating it as dead (env or
`$KEEL_HOME/config.json` only -- neither `connect` nor `status` expose a flag for it).
It defaults to one full long-poll cycle's worst case plus slack (50s with `connect`'s
own defaults) so a runtime merely waiting on a slow long-poll is never mistaken for
dead; see `specs/021-keel-runtime-status/research.md` §4.

## Which executor runs

There are two hosts, Claude Code and GitHub Copilot, and each has an executor. Keel never ships a
host CLI inside anything of ours: each is self-updating and each authenticates against an account
that is *the founder's*, so a frozen copy would be stale within a week and unable to log them in.
Both are found on `PATH`.

```
1  explicit:  --executor  >  KEEL_EXECUTOR  >  $KEEL_HOME/config.json["executor"]
              -> that one, always, even if its CLI is missing (it reports per job)
2  host:      --host, then the environment this process was launched into
              COPILOT_AGENT_SESSION_ID non-empty, or COPILOT_CLI == "1"   -> copilot
              CLAUDECODE == "1"                                           -> claude
              AI_AGENT starts with "github_copilot" / "claude-code"       -> copilot / claude
              -> exactly one answer, take it; two different answers, take NEITHER
3  PATH:      exactly one of `copilot` / `claude` on PATH  -> that one
4  both on PATH and nothing above decided  -> claude, and say so
5  neither on PATH -> claude, and print KEEL_EXECUTOR_UNAVAILABLE; the runtime still
                      connects and reports EXECUTOR_UNAVAILABLE per job
```

**Two host answers mean no answer**, and that is not hypothetical: `COPILOT_AGENT_SESSION_ID` leaks
arbitrarily deep down a process tree — it means "somewhere in my ancestry", never "my parent" — so
`copilot` running *inside* Claude Code carries both hosts' markers at once.

**The runtime says which, always**, on the line after `KEEL_ENVIRONMENT=`:

```
KEEL_EXECUTOR=copilot source=host binary=/opt/homebrew/bin/copilot version=GitHub Copilot CLI 1.0.83. model=auto
KEEL_EXECUTOR=claude source=ambiguous-path  # both CLIs on PATH; pass --executor to choose
KEEL_EXECUTOR_UNAVAILABLE=copilot           # not on PATH; jobs report EXECUTOR_UNAVAILABLE
```

`source` is one of `flag`, `env`, `config`, `host`, `path`, `ambiguous-path`, `default` — the
founder and the referee should both see *why*, not only *what*.

## Executors

- **`claude`** (default; **`claude-code` is a permanent accepted alias**) — the real executor.
  Invokes the `claude` CLI in a
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
    --max-turns <N>                 # KEEL_JOB_MAX_TURNS, default 6
    --max-budget-usd <amount>       # KEEL_JOB_BUDGET_USD, default 1.00
    --output-format stream-json --verbose  # one JSON event per line, not raw prose
    --json-schema <contract>        # the job's own response contract, enforced by the CLI
    --system-prompt <fixed text>    # runtime-owned, identical for every job
  ```

  The whole invocation is given `KEEL_JOB_TIMEOUT_SECONDS` (default **300s**) of wall
  clock, after which the runtime raises `ExecutorTimeout` and the job fails. It is a
  ceiling on a stuck job, not a target: a healthy breakdown answers in about 90s. The
  number was hard-coded at 120s until keel-e2e-eval's instruction eval measured the real
  spread of an assumption job -- 81 to 120 seconds, six of twenty-one hitting the limit,
  the slowest survivor eleven seconds clear -- and it now resolves like every other key.

  with the prompt on **stdin** (never argv), `cwd` an empty per-job directory under
  `$KEEL_HOME/jobs/<job_id>/`, and an allow-listed environment (`PATH`, `HOME`, `USER`,
  `LANG`, `LC_*`, `TMPDIR`, `TERM`, plus any `ANTHROPIC_*`/`CLAUDE_*` variable the CLI
  needs for its own auth — never `KEEL_HOME`, never `KEEL_BASE_URL`). `--bare` is
  deliberately **not** used: it skips keychain reads and the CLI reports "Not logged
  in". `--output-format json` was replaced by `--output-format stream-json --verbose`
  (spec amendment FR-010) so a refused structured-output attempt is visible mid-stream,
  not only in the final tally: stdout is one JSON object per line (`system`,
  `assistant`, `user`, `rate_limit_event`, `result` event types observed against Claude
  Code 2.1.259); the last `result` event is the envelope, same shape as the old
  `--output-format json` output. The result comes from that envelope's
  `structured_output`, never scraped from stdout. **Requires Claude Code ≥ 2.1.259.** An
  older CLI without `--json-schema` exits non-zero and the job fails `LLM_UNAVAILABLE`.

  **The `--json-schema` envelope now carries an `if`/`then` chain**: a `COMPLETED` answer must
  have a `result`, a `NEEDS_INPUT` answer must have `questions`, on top of the flat
  `{outcome, questions?, result?}` object with `additionalProperties: false`. Both keys used to
  be simply optional, and staging measured what that costs -- the model answered
  `{"outcome": "COMPLETED"}` with no `result`, the CLI accepted it because the schema permitted
  it, and `response_validator` refused it afterwards, too late for the model to answer again.
  The schema now says exactly what the runtime checks. (`if`/`then` rather than `anyOf`,
  `oneOf` or `allOf` because the CLI passes this document through as a tool's `input_schema`,
  where the API refuses all three combinators at the top level -- and refuses a schema with no
  `type` at all. Both refusals were measured in CI, not guessed; `keel_runtime/executor.py`'s
  `_build_envelope_schema` carries the run numbers.)

  When the CLI's own turn budget runs out (`result.subtype == "error_max_turns"`) and a
  refused attempt was seen along the way (a `user` event's `tool_result` beginning
  "Output does not match required schema"), the runtime runs the CLI **once more** —
  same prompt, plus a final `RECOVERY` section that quotes the refusal and asks for the
  named field cut to half its length (spec amendment FR-011). Never more than one such
  pass; a second failure fails the job. `/fail`'s message for an exhausted-turns job
  names the last schema refusal (`LLM_UNAVAILABLE: the answer never fit its shape --
  <refusal>`); for a budget overrun it names the cap (`LLM_UNAVAILABLE: the job cost
  more than $<cap>`).

  Every human- or model-authored string in the prompt — the founder's framing text, a
  participant's answers, earlier turns — sits inside one `<<<KEEL-DATA <nonce>>> ...
  <<<END KEEL-DATA <nonce>>>` fence with a fresh per-job random nonce, under a heading
  that says it is source material, not an instruction; the fixed system prompt states
  the same rule.

  The per-job directory (`$KEEL_HOME/jobs/<job_id>/`) holds `envelope.json` (the final
  `result` event, verbatim — both passes' `num_turns`/`total_cost_usd` summed and
  `recovery_pass: true` added when the recovery pass ran), `request.json` (the prompt
  sections that were sent), and `events.jsonl` (the raw `stream-json` events, both
  passes' when a recovery pass ran) once the job finishes, success or failure —
  diagnostic logs, kept across jobs but pruned to the newest 50 each time `connect`
  starts.

- **`copilot`** — the second real executor (spec `005-copilot-executor`; design §5.4). Same ABC,
  same `{outcome, questions?|result?}` dict, same three exceptions, so `poller` cannot tell which
  host answered. **The prompt is the runtime's, not the host's**: `build_prompt` is shared byte for
  byte, because two hosts sent different prompts measure two different things.

  ```
  copilot -p ""                     # empty operand: the rendered prompt is on **stdin**
    --excluded-tools=<name>         # one flag per name, every tool this CLI ships
    --disable-builtin-mcps --no-custom-instructions --no-ask-user
    --no-remote --no-remote-export --no-auto-update --no-color
    --output-format json --log-level none
    --max-ai-credits <n>            # n >= 30, a soft cap, never a dollar figure
    -C <job_dir>
    [--model <slug>]                # KEEL_COPILOT_MODEL; unpinned prints model=auto
  ```

  **The prompt goes on stdin on both executors, never in argv** — `claude -p` and `copilot -p ""`
  each read it from there (measured against Copilot CLI 1.0.83; there is no `--prompt-file` and
  no `@file` on that CLI). On Windows both CLIs are npm `.cmd` shims dispatched through
  `cmd.exe`, which cuts an argv element at its first newline, so an argv-borne prompt reached
  the model as its first line only.

  **And on Windows the shim itself is no longer what gets launched.** The flags travelled the
  same road as the prompt, and staging measured where that ends: `claude.CMD` launched through
  `cmd.exe`, exit 255 with no output, or `The filename, directory name, or volume label syntax
  is incorrect.` -- a batch interpreter re-parsing `--system-prompt`'s sentence and
  `--json-schema`'s JSON. The runtime now **reads the npm shim** and launches what the shim itself
  would have launched, parsed out of its own text rather than guessed: `[node, <the .js it names>,
  ...]` where the package has a JavaScript bin (`@github/copilot`'s `npm-loader.js`), and the
  executable directly where it has a native one (`@anthropic-ai/claude-code` installs
  `bin/claude.exe`, so its shim contains no JavaScript at all). Either way, no `cmd.exe` in the
  chain. A shim naming neither, or a machine with no `node` for a JavaScript one, falls back to
  launching the shim exactly as before and prints one `KEEL_LAUNCH via=cmd.exe ... --` line into
  the launch log saying which and why. Nothing changes on macOS or Linux.

  This CLI has **no `--json-schema`, no `--system-prompt`, no turn limit and no timeout flag**. The
  first two move into the prompt text, above TASK and *outside* the KEEL-DATA fence — they are the
  executor addressing the model, not source material it must never follow. So **on Claude the
  schema is enforced by the CLI; on Copilot it is asked for in prose and checked afterwards by the
  runtime**, which is why `jsonschema` being optional matters most here: the stdlib subset
  validator in `response_validator.py` is the only thing between a model's prose and the poller.
  The timeout is ours, at the same `KEEL_JOB_TIMEOUT_SECONDS` (300s) the Claude path uses.

  **The exit code is not a success signal.** Measured against Copilot CLI 1.0.83: a run whose every
  tool was denied and whose task therefore failed exits **0**; an unauthenticated run exits **1**
  with no JSONL at all. Success is decided by the JSONL: any `session.error` is a failure; the
  answer is the last `assistant.message` whose `data.phase == "final_answer"` (a tool-calling turn
  emits one with empty content, so "the last assistant message" is the wrong rule), an optional
  ` ```json ` fence stripped, then validated through the same validator the Claude path uses.

  **The closed shape is verified per job, not asserted once.** `--available-tools ""` was measured
  to be *ignored*; only `--excluded-tools` with every name enumerated reaches `tool_count: 0`. An
  enumeration rots the day Copilot ships a new tool — and it had already rotted when this was
  written — so **every job's own `session.usage_checkpoint` must report `tool_count: 0`**, and a
  non-zero count fails the job before its answer is used.

  **No dollar figure is invented.** Copilot reports `usage.premiumRequests`, so `envelope.json`
  carries `premium_requests` and no `total_cost_usd` at all — absent, not zero.

  **Authentication**, in the CLI's own order: `COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN`
  > the stored OAuth credential. An `ExecutorAuthFailure` is raised only on an **observed** marker:
  three genuinely unauthenticated runs were produced on 2026-09-09 with an isolated `COPILOT_HOME`,
  and all three exit 1 with **completely empty stdout** and one message on stderr
  (`No authentication information found.` / `Classic Personal Access Tokens (ghp_) are not
  supported by Copilot.` / `Authentication token found but could not be validated.`). Anything
  else, including an unrecognised `session.error`, is `ExecutorUnavailable` — which fails the safe
  way. The recordings are in `tests/fixtures/copilot/`.

  Each executor's environment allow-list is its own: `copilot` gets `COPILOT_*`, `GH_TOKEN`,
  `GITHUB_TOKEN`, `GH_HOST` and the common set; `claude` gets `ANTHROPIC_*`/`CLAUDE_*` and the
  common set; neither gets the other's, and neither gets `PYTHONPATH` or any other interpreter
  variable.

  **Status: "runs, unmeasured."** In the design's own words. A host is listed as *supported* only
  when four things are true — this runtime's suite green with that CLI installed, keel-e2e-eval
  S-001 green through it, the instruction eval's run of record green on it at the current
  `MARKS_VERSION`, and the release notes naming the CLI version range. Only the first is true
  today.

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
`SOLUTION_REFRAME`, `COMMERCIAL_REFRAME`, `INTERPRET`, `BRIEF`, and the three
`<SCREEN>.correction` screens), each a list of entries consumed in order (the last entry
repeats once the list is exhausted). The screen is never LLM-derived — it is inferred from
the request payload's own `context` keys, so the same poll loop, the same
`response_validator`, and the same `complete`/`fail` calls run exactly as they do with any
other executor.

**The inference table is loaded, not written.** keel-cloud's `ScreenContextBuilder` writes
every key for its screen, filling an absent value with `null` rather than omitting the key,
so each screen's key set is fixed and complete and an **exact key-set match** is the whole
rule. The table comes from keel-cloud's own export —
`./gradlew -q screenContracts --args="export <dir>"`, its `context-keys.json` — reached by
`--context-keys`, then `KEEL_CONTEXT_KEYS`, then `$KEEL_HOME/config.json`, and finally the
copy bundled at `keel_runtime/testing/contracts/context-keys.json`. That bundled copy is
regenerated from keel-cloud and never hand-edited; the commit it came from is recorded in
[`AMENDMENT-measured-beliefs.md`](../specs/001-scripted-executor/AMENDMENT-measured-beliefs.md).
An unknown key set still raises `ExecutorUnavailable` naming the keys: the table is strict on
purpose, because a loose executor would answer the wrong screen silently — and that is
precisely how the last round of drift was caught at all.

`--script` and `--context-keys` are only meaningful with `--executor scripted`; given with
any other executor each is ignored with a warning. `--script` falls back to `KEEL_SCRIPT`,
then to the bundled default, `keel_runtime/testing/scripts/countly-problem.json` — the
`PROBLEM` stage of keel-cloud's frozen golden corpus entry `01-countly`, generated by
`tools/generate_bundled_script.py` and never written by hand. It replaced
`payroll-exceptions.json`, which was written entirely in the retired
`claimType`/`stance`/`perAnswer`/`evidence` shapes and could no longer be applied by
keel-cloud at all. keel-e2e-eval hands this runtime a per-scenario script through
`KEEL_SCRIPT`, because the runtime is only ever started through keel-connect-skill's own
script. See [`specs/001-scripted-executor/spec.md`](../specs/001-scripted-executor/spec.md)
and its amendment.

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
python3 -m unittest discover -s tests -t .   # stdlib only
python -m pytest -q                          # what CI runs
```

wired into the Java build's `check` task as `keelRuntimeTest` (spec SC-001).

The only test-only dependencies are `pytest` and `PyYAML` (the latter for
`tools/generate_bundled_script.py`, which reads keel-cloud's golden corpus); both are declared as
the `dev` extra, `pip install -e ".[dev]"`. **Neither `keyring` nor `jsonschema` is ever installed
in CI**, and every row of the matrix asserts they are absent before running the suite: the
`0600` credential file and the stdlib subset validator are what founders run, so they are what is
tested (invariants R-1 and R-2).

## License

Apache License, Version 2.0 — see [`LICENSE`](LICENSE).
