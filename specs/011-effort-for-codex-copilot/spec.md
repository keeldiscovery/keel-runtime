# Feature Specification: The effort reaches Codex and Copilot — the second half of the pin on all three hosts

**Feature Branch**: `011-effort-for-codex-copilot` (branch `011-effort-for-codex-copilot`, off master `94e7cf1` = 0.6.0)

**Created**: 2026-10-03

**Status**: Approved by the founder, 2026-10-03 — *"Terra for standard and Luna for light [for
Codex and Copilot], then the runtime learns to pass the effort for Codex and Copilot… I agree to
all the changes."*

**Input**: keel-cloud spec `055-openai-pins` (table v8: `efforts.codex.standard = efforts.copilot
.standard = "medium"`) and the screen behind it,
`keel-cloud/canon/drafts/codex-terra-luna-screen-2026-10-03.md` §6 (*Effort on Codex: what was
measured, and what the runtime cannot yet do*); keel-cloud `canon/designs/model-routing-design.md`
§4 (the `efforts` block), §5 (the wire's seventh key), §6 (the runtime's one rule), §8 (no
cloud-side translation); this repository's own spec `010-job-names-the-effort`, whose shape this
one copies for the other two hosts, and `009-model-routing`.

## Scope

`keel_runtime/executor.py` (two `_build_argv`s, two `_invoke`s, six call sites, two ladders, one
refusal), two new fixture recordings with their `MANIFEST.json` rows, `tests/test_effort_routing.py`,
`README.md`, the version. **Out of scope**: the poller (`_effort_for` already reads
`request_payload["effort"][<host_key>]` for every host — spec 010 FR-002 — and nothing there
moves), the `efforts` rows' production (keel-cloud spec 055), the eval's own harness (keel-e2e-eval
`026-codex-effort`, which is the referee's half and is already written), and the skill's bundled
runtime refresh (keel-connect-skill still vendors 0.5.1; `make runtime` there is the founder's
call).

## The one sentence

**`CodexExecutor._build_argv` and `CopilotExecutor._build_argv` take an `effort`, and when the job
named one append it after the model — Codex as `-c model_reasoning_effort=<level>` because that CLI
has no effort flag, Copilot as `--effort <level>` — each checked against its own CLI's recorded
ladder and refused per job, by name, when the word is not on it; both `_invoke`s thread it to every
pass of the job exactly as `ClaudeCodeExecutor` does; an argv without an effort does not move a
byte; version 0.7.0.**

## Why this exists, in one paragraph

Spec 010 closed half the gap: a founder's own Claude Code now runs the certified *pair*, not the
certified model at the CLI's own `xhigh`. It left Codex and Copilot alone on purpose — *"neither
CLI's argv has an effort flag to pass it to"*, which on 2026-09-30 was the measured truth of this
runtime and not of the CLIs. On 2026-10-03 the screen measured both: `codex exec` takes
`-c model_reasoning_effort=<level>` beside `-m` on the founder's ChatGPT login (one closed probe,
`ok` in 3.4 s, no `error` event), and `copilot --help` lists `--effort, --reasoning-effort <level>`
with seven choices. The same day keel-cloud's table v8 put `gpt-5.6-terra` at `medium` on both
OpenAI `standard` rows. The screen that backs that row ran at the *catalogue default*, which was
`medium` on the day and which can move under a pin (`gpt-6-astra`'s is already `low`); the only
way a certificate can state its effort is to have passed it, and until this spec a 0.6.0 Codex
executor dropped the word on the floor.

## What was measured before anything was written (2026-10-03, the founder's Mac)

1. **Codex has no effort flag.** `codex exec --help` on codex-cli 0.154.0 has no `--effort`; the
   effort is a config override through the generic `-c, --config <key=value>`, whose help text
   names neither the key nor a ladder and says the value *"is parsed as TOML"*. **Recorded as a
   fixture** (`tests/fixtures/codex/exec-config-help.txt`, the `-c` entry verbatim). The key,
   `model_reasoning_effort`, and its acceptance beside `-m` are the screen's measurement (§6.2):
   one closed probe on the ChatGPT login answered `ok`, 12,766 input / 5 output / 0 reasoning
   tokens, no `error` event. Nothing in the `--json` stream names the effort that ran — so, as for
   the model, **the argv is the record**.
2. **Codex's ladder is the catalogue's, and it is per model.** `~/.codex/models_cache.json` (read,
   not called) gives `supported_reasoning_levels` per model: every visible model lists `low`,
   `medium`, `high`, `xhigh`; `gpt-5.5` lists exactly those four; `gpt-5.6-luna` adds `max`;
   `gpt-5.6-terra`, `gpt-5.6-sol` and `gpt-6-astra` add `max` and `ultra`. `default_reasoning_level`
   is `medium` for terra and luna, `low` for astra. **The runtime's ladder is the four-word
   intersection** (A-2). *The screen report's §6.2 states the ladder as the four words "every
   visible model" supports — true as the intersection, but terra and luna list more; recorded here
   so nobody reads the four as the whole catalogue.*
3. **Copilot has the flag, with a ladder in its help.** `copilot --help` on GitHub Copilot CLI
   1.0.83: `--effort, --reasoning-effort <level>  Set the reasoning effort level (choices: "none",
   "minimal", "low", "medium", "high", "xhigh", "max")`. **Recorded as a fixture**
   (`tests/fixtures/copilot/effort-help.txt`, verbatim). **No call was made**: whether a given model
   honours the flag on the founder's plan is unmeasured, and that is keel-cloud's screen to spend
   (spec 055 owes the two `--model` probes and one `K=03-lullaby` screen on Copilot before its rows
   are trusted).
4. **The poller already reads it for every host.** `_effort_for(executor, payload)` keys on
   `executor.host_key`; spec 010's tests prove it answers `"high"` for a `codex` executor given
   `{"effort": {"codex": "high"}}`. Only the executors ignored it.

## Requirements

- **FR-001** `CodexExecutor._build_argv(job_dir, model=None, effort=None)`: when `effort` is
  truthy, append `["-c", f"model_reasoning_effort={effort}"]` **after** `["-m", model]`; an argv
  built with no effort is byte-identical to 0.6.0's.
- **FR-002** `CopilotExecutor._build_argv(job_dir, model=None, effort=None)`: when `effort` is
  truthy, append `["--effort", effort]` **after** `["--model", model]`; the same byte-identity.
- **FR-003** Both `_invoke`s take `effort` and pass it to `_build_argv`; both `execute`s read
  `request.effort` the way `ClaudeCodeExecutor.execute` does (a non-empty stripped string, else
  `None`) and pass it on **every** pass — the first, the unpinned retry (model `None`, effort kept;
  spec 010 FR-005's reason) and the recovery pass.
- **FR-004** `CODEX_EFFORT_LADDER = ("low", "medium", "high", "xhigh")`, exported; a test reads the
  fixture's `MANIFEST.json` row back against it.
- **FR-005** `COPILOT_EFFORT_LADDER = ("none", "minimal", "low", "medium", "high", "xhigh",
  "max")`, exported; a test reads `effort-help.txt` back against it.
- **FR-006** A word off the host's ladder is **refused per job, by name, before any process is
  spawned**: `ExecutorUnavailable` whose message quotes the word and the ladder, so the poller fails
  *that job* as `LLM_UNAVAILABLE` with the sentence, and runs nothing at a guess. Exact match only
  — no case-folding, no stripping (the poller already stripped). Nothing is substituted.
- **FR-007** `ClaudeCodeExecutor` is untouched: spec 010 FR-008's pass-through stands for the one
  CLI whose `--help` names its ladder and which refuses a bad word at the flag.
- **FR-008** The runtime still keeps **no** effort knob (spec 010 FR-007): no flag, no `KEEL_*`
  variable, no config key. `ThereIsNoEffortKnobTest` stands unchanged.
- **FR-009** Nothing new on the completion report (spec 010 A-4 stands): `execution` keeps its
  five keys.
- **FR-010** README: the three ladders in one table, the flag on each host's argv block, the v8
  example on the wire; `connect`'s `KEEL_EXECUTOR=` line unchanged.
- **FR-011** Version **0.7.0**, in `keel_runtime/__init__.py` and `pyproject.toml`.

## Success Criteria

- **SC-001** `CodexExecutor._build_argv(d)` and `(d, "gpt-5.6-terra")` carry no `-c`;
  `(d, "gpt-5.6-terra", "medium")` ends `-m gpt-5.6-terra -c model_reasoning_effort=medium`.
- **SC-002** `CopilotExecutor._build_argv(d, "gpt-5.6-terra", "medium")` ends
  `--model gpt-5.6-terra --effort medium`; without an effort, no `--effort`.
- **SC-003** Through the fake CLIs: a job carrying `{"effort": {"codex": "medium"}}` reaches
  `codex` with the override after `-m`; the same for `copilot`; a job with no effort sends no flag;
  the effort survives the unpinned retry on both hosts.
- **SC-004** `effort="ultra"` on either host raises `ExecutorUnavailable` naming `'ultra'` and the
  ladder, and the fake CLI records **no** invocation.
- **SC-005** Every word on each ladder is accepted and only those; `max` is accepted on Copilot
  and refused on Codex; `none` the reverse.
- **SC-006** `python3 -m pytest -q` green on Python 3.9+; the pre-0.7.0 argv equality tests in
  `test_codex_executor.py` and `test_copilot_executor.py` pass unchanged.

## Assumptions and judgement calls

- **A-1 — A config override is this host's flag.** Codex has no `--effort`; `-c
  model_reasoning_effort=<level>` is what the CLI offers and what the screen measured accepted.
  The alternative — `CODEX_HOME/config.toml` — is process-wide and a file, and spec 010 A-1 already
  said why a per-job value belongs on a per-job argv. `--ignore-user-config` stays: the override is
  on the argv, not in the founder's own `config.toml`, so the two do not meet.
- **A-2 — The Codex ladder is the catalogue's intersection, and the runtime checks it (unlike
  Claude's).** Spec 010 A-3 declined to validate because two parties already refused a bad word —
  the cloud at startup, the CLI at the flag. On Codex the second party is missing: `-c` takes any
  TOML and the help names no ladder, and nothing measured what the CLI does with
  `model_reasoning_effort="ultra"` on a model that lists no `ultra` — run at its default, error, or
  something else. A runtime that passed it through would be the one thing in the chain nobody can
  check. So the ladder is the four words every visible model supports, exact match, and a word off
  it fails one job by name. `max` and `ultra` exist for some models and are refused here on purpose:
  a per-model ladder would need the catalogue read per job, and the cloud's table cannot name a
  word for one model only. If a row ever wants `max` on Codex, the ladder widens by one word in
  one commit, with the catalogue read that day beside it.
- **A-3 — Copilot is checked too, for symmetry and for the message.** Its CLI would refuse at the
  flag (commander `choices`), so the second party exists; the runtime refuses first anyway so the
  per-job failure names the ladder in this runtime's words rather than commander's, and so the two
  OpenAI hosts have one rule. The cost is one tuple that must match the fixture, and a test holds
  them together.
- **A-4 — `ExecutorUnavailable`, not `InvalidResponse`.** The job did not produce a bad answer; it
  could not be run as named. The poller maps it to `LLM_UNAVAILABLE` with the sentence, the cloud
  sees it on that job, and nothing is retried unpinned (the retry is for a refused *model*).
- **A-5 — The effort survives the unpinned retry on both hosts** (spec 010 FR-005, A-2): the retry
  answers a *model* refusal; dropping the effort would answer it with two changes, the second
  silent, and on Codex the second one would be invisible — the stream never names the effort.
- **A-6 — Claude Code's pass-through stays.** The three ladders differ and the three mechanisms
  differ; one rule per host, each written beside its measurement.

## What the runtime does not do, still

- Report the effort back on completion (spec 010 A-4).
- Read `~/.codex/models_cache.json` at runtime: the ladder is a constant with its measurement
  recorded, and the catalogue is a file on one machine, not a fact the runtime should depend on.
- Cut the plugin release: keel-connect-skill vendors 0.5.1 and a founder on that bundle runs the
  catalogue default until it is re-bundled — the founder's call.
