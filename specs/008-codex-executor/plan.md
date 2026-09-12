# Implementation Plan: The third host — `CodexExecutor`

**Branch**: `008-codex-executor` | **Date**: 2026-09-12 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md) (FR-001..011, SC-001..004) and keel-cloud
`canon/designs/keel-skill-design.md` decision 11's five-item pattern, §5.3, §9 C-1..C-8 read
for a third host.

## Summary

Measure first, then one class, one resolver row, one flag, and a lot of recording — the same
shape as spec 005, because that spec is what made this one a day.

`CodexExecutor` is `CopilotExecutor`'s design with Codex's flags. The two CLIs share the
constraint that decides the prompt's shape: neither takes a system prompt as a flag, and neither
can enforce Keel's either/or envelope for us (Copilot has no schema flag; Codex has one that
hands the schema to OpenAI's strict structured outputs, which refuse it). So both get
`_render_copilot_prompt` — SYSTEM and RESPONSE above TASK — and the runtime's own validator.
Where they differ is what "closed" means on the command line: Copilot takes tool names to
exclude and reports a `tool_count` per session; Codex takes *feature* names to disable and
reports nothing about availability, only use. The closed-shape check is therefore two things on
this host: a recorded pair proving the flags remove the tools, and a per-job scan of the stream
for any item that is not an answer.

## Technical Context

- **Language**: Python 3.9 floor, stdlib only under `keel_runtime/` (R-1, R-2).
- **The CLI**: codex-cli 0.154.0, `npm i -g @openai/codex`; `codex login` (ChatGPT plan in the
  browser, `--device-auth`, or `--with-api-key`); credential under `$CODEX_HOME` (`~/.codex`).
- **Non-interactive mode**: `codex exec [-]`, prompt on stdin when the operand is `-`; `--json`
  JSONL; `--ephemeral`; `--sandbox read-only|workspace-write|danger-full-access`; `--disable
  <feature>`; `-c key=value`; `-m model`; `-C dir`; `--skip-git-repo-check`;
  `--ignore-user-config`; `--output-schema FILE` (unused, see spec measurement 4); `-o FILE`.
- **Event stream** (measured): `thread.started{thread_id}`, `turn.started`,
  `item.started|item.completed{item:{id,type,...}}` with item types `agent_message{text}`,
  `command_execution{command,exit_code,aggregated_output}`, `reasoning`; `turn.completed{usage}`;
  `error{message}`; `turn.failed{error:{message}}`.
- **Host markers** (measured): `CODEX_THREAD_ID`, `CODEX_SESSION_ID`.

## Project structure

```
keel_runtime/executor.py      CODEX_* constants, _codex_* readers, CodexExecutor, _make_codex
keel_runtime/config.py        EXECUTOR_BINARIES, ENV_HOST_MARKERS, host_from_environment,
                              resolve_executor (three CLIs), ENV_CODEX_MODEL, resolve_codex_model
keel_runtime/cli.py           --executor codex, --host codex, --codex-model, model=default line
tests/test_codex_executor.py  18 tests against the recordings
tests/fixtures/codex/         seven recordings and MANIFEST.json
README.md                     "Which executor runs" for three hosts; the `codex` bullet
```

## Design decisions

1. **Feature flags are the closed shape, and the pair of recordings is the proof.** A list of
   tool names would be the wrong abstraction on this CLI: the shell is a feature, images are a
   feature, and `codex features list` is the enumeration the CLI itself maintains.
2. **No `--output-schema`.** Strict mode is the API's, not the CLI's, and Keel's envelope cannot
   be strict without lying (a `result` on a NEEDS_INPUT answer). The prompt carries the schema;
   the validator enforces it; the recovery pass names the missing key.
3. **`--ignore-user-config`, `--ephemeral`, `--sandbox read-only`, all three.** The founder's
   own `config.toml` — their MCP servers, skills, hooks — is theirs and not a job's; a job writes
   no session; and the sandbox is belt to the flags' braces, not the closed shape itself.
4. **The parent session's `CODEX_*` do not travel.** A job's `codex` inheriting
   `CODEX_THREAD_ID` or `CODEX_SANDBOX_NETWORK_DISABLED=1` from the skill's own Codex session
   would believe things about itself that are not true. `CODEX_HOME` alone travels: it is where
   the credential is.
5. **Tokens, never dollars** (C-7). A ChatGPT plan has no per-token price; `tokens` is the
   envelope's unit and `total_cost_usd` is absent.
6. **`model=default`, not `model=auto`.** Copilot's `auto` is a router; Codex's unpinned run is
   one model, the account's default. The word on the line is the truth of that host.

## Phases

- **Phase 0, measurement**: the seven recordings, in the order spec.md lists them. Done before
  the class was written, as spec 005 did.
- **Phase 1, the executor**: constants, readers, `CodexExecutor`, factory, `_EXECUTORS`.
- **Phase 2, selection**: config markers and PATH step, CLI flags and the startup line.
- **Phase 3, tests and README**.
- **Sibling commits**: the skill's `detect_host`; the marketplace's Codex manifest; the
  instruction eval's `--host codex` and the harness's scrub list.
