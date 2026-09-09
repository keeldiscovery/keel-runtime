# Contract: `keel-runtime disconnect` CLI output

**This is the stable, external contract** (spec FR-012) — the one thing a caller in another
repository (keel-connect-skill's `scripts/keel_disconnect.py`, keel-e2e-eval's `make down`) is
allowed to depend on. Every other detail of this feature's implementation (the module layout, the
poll interval, the two bounds, the heartbeat file's own schema) may change; this contract may not,
without a spec update here.

Its sibling is keel-cloud's
`specs/021-keel-runtime-status/contracts/status-cli-output.md`, written in the same five parts and
read by the same callers. Where the two overlap they agree by construction: `disconnect` resolves
its home through the same `config.load_status_config`, and reports the address through the same
resolution `status` reports it with.

## Invocation

```text
python3 -m keel_runtime disconnect [--home PATH] [--base-url URL]
```

- `--home` follows the same precedence as `connect` and `status` (flag > `KEEL_HOME` env > the home
  derived from the resolved base URL > `~/.keel`), and resolves the **identical directory**
  `status` resolves from the same inputs.
- `--base-url` names a Keel, and since spec `004-shipped-runtime` the home follows the address —
  so it is a way of naming the home without computing a host slug. It is never used to reach the
  network. No other flag is accepted.
- Exits **0** in every case described below — nothing running is a normal, successful answer, and
  so is a process that would not die. A non-zero exit is reserved for a genuine usage error (e.g.
  an unknown flag), which prints its message to stderr, not the JSON contract below.
- Prints **exactly one line** of JSON to stdout, newline-terminated, nothing else on stdout (no
  banner, no progress text — a caller can safely `json.loads(subprocess.check_output(...))`).
- Never makes a network call (spec FR-006, design D9). It is as cheap and as network-independent
  as `status`, which is what makes it safe in a teardown script or on a laptop on a train.
- Bounded: **15 seconds worst case** — `SIGTERM`, ten seconds of grace, `SIGKILL`, five more.
- **Idempotent**: a second run against the same home is `not_running`.
- **Never touches the credential** — not `credentials.json`, not the keyring. It stops a process;
  it does not forget a machine. The next `keel connect` on this home reconnects with no device code
  and no browser.

## Output shapes (exhaustive — spec FR-002, FR-005)

Every shape also carries the three **address keys** — `home`, `base_url` and `environment` — which
are always present and are documented once, below the four shapes.

**Stopped** (the pid was alive, was signalled, and is now gone):

```json
{"outcome": "stopped", "pid": 41213, "waited_ms": 84, "signal": "SIGTERM"}
```

`signal` is `"SIGTERM"` when the runtime left within the grace, and `"SIGKILL"` when it had to be
escalated — in which case `waited_ms` is at least the grace. `waited_ms` is measured from the first
signal, not from process start, so a caller can see the difference between a runtime that stopped
in 80ms and one that took nine seconds to leave a job.

**Not running** (no readable heartbeat for this home — missing file, unreadable file, malformed
JSON, or JSON short a required field are one answer, exactly as `status` treats the same four
cases):

```json
{"outcome": "not_running"}
```

**Stale pid cleared** (a heartbeat naming a pid that is not alive — the trace of a runtime that
died without running its shutdown handler; the file was removed and **nothing was signalled**):

```json
{"outcome": "stale_pid_cleared", "pid": 40118}
```

**Timeout** (the pid survived both signals within the bound; **the heartbeat is deliberately left
in place**):

```json
{"outcome": "timeout", "pid": 41213, "waited_ms": 15003}
```

**The address keys**, on all four shapes:

```json
{"outcome": "not_running",
 "home": "/Users/you/.keel/localhost-18081",
 "base_url": "http://localhost:18081",
 "environment": "localhost:18081"}
```

- `home` is the directory that was acted on — the one `status` names for the same inputs.
- `base_url` and `environment` are *which Keel*: `"cloud"` for the built-in default, `host:port`
  for anything else. When the heartbeat was readable they describe the Keel **the stopped process
  was connected to** (its own record), not what a fresh resolution would pick now; otherwise they
  describe what resolves now.
- `base_url` and `environment` are `null` when nothing names a Keel at all. `home` is never null.
- `executor` and `executor_on_path`, which `status` carries, are deliberately **absent**: no
  executor takes part in a disconnect.

## Guarantees a caller may rely on

1. Every key present in a given shape above is present in every occurrence of that shape — no key
   is ever conditionally omitted within a shape. `outcome`, `home`, `base_url` and `environment`
   are present in **all four**.
2. No key outside these four shapes is ever added without this contract file changing first.
3. `outcome` is always one of `stopped`, `not_running`, `stale_pid_cleared`, `timeout`, and it is
   the whole answer — the exit code carries no information beyond it. **`timeout` is the one
   outcome a caller must treat as a failure**, and it says so by name.
4. `stopped` is emitted only after the pid was observed **not alive** — it is a proof, not a
   send-and-hope. A caller told `stopped` may start a new runtime on this home immediately, with no
   risk of two runtimes against one credential.
5. On `timeout` the heartbeat file is still there, on purpose, so `status` keeps reporting the
   process that is still polling. A caller told `timeout` must **not** start a runtime on this
   home: the old one is still claiming jobs.
6. `pid`, where present, is the pid this home's heartbeat named at the moment the command ran. Only
   a pid read from that file is ever signalled — there is no way to hand this command a pid to
   kill.
7. `stale_pid_cleared` implies **no signal was sent to any process**, and that the heartbeat file
   is gone.
8. `waited_ms` is present exactly on `stopped` and `timeout` — the two outcomes that involved
   waiting — and is measured from the first signal.
9. No outcome removes, rewrites or reads any file in the home but `runtime.heartbeat.json`. The
   credential survives every one of them.
