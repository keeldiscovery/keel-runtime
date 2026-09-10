# Amendment: the prompt transport (2026-09-10)

Amends `spec.md` / `plan.md` invariant **C-2**. Everything else in spec 005 stands unchanged:
the allow-listed environment (C-4), the 300s caller-side timeout, the JSONL parsing, the
`--excluded-tools` enumeration (C-1) and `--no-auto-update` are exactly as they were.

## 1. The finding

`CopilotExecutor._build_argv` sent the whole rendered prompt as **one argv element**
(`[binary, "-p", prompt]`), and that prompt is always multi-line — `_render_prompt` joins its
sections with `"\n"`.

On Windows a real Copilot CLI install is `copilot.cmd` (the npm shim; the same shape as
`claude.cmd`). Launching a `.cmd` is dispatched through `cmd.exe` by the operating system's own
loader, `shell=True` or not, and **`cmd.exe` cuts an argument at its first `\n`**. The Windows CI
matrix added in PR #1 caught it: the fake CLI recorded a prompt argv reading exactly `"SYSTEM"` —
the literal first line of `_render_copilot_prompt`'s output.

The consequence for a Windows founder is the worst kind: no error anywhere. The CLI exits 0, the
closed shape verifies, the JSONL parses, and the model answers a one-line version of a question it
was never fully asked. Seven tests in `tests/test_copilot_executor.py` were skipped on Windows
rather than fixed, because fixing it needed the real CLI to measure against.

## 2. The measurement

GitHub Copilot CLI **1.0.83**, macOS 25.5.0 (Apple Silicon), logged in, isolated `COPILOT_HOME`,
2026-09-10. Tiny prompts throughout.

### 2.1 What `--help` offers

`copilot --help | grep -iE "prompt|stdin|file"` — the only prompt-bearing options are:

```
  -i, --interactive <prompt>            Start interactive mode and automatically execute this prompt
  -p, --prompt <text>                   Execute a prompt in non-interactive mode (exits after completion)
  --attachment <path>                   Attach a file (image or native document) to the initial prompt
```

**There is no `--prompt-file`.** `@`-prefixing is documented for exactly one option,
`--additional-mcp-config`, and for nothing else. Nothing in `--help` mentions stdin at all.

### 2.2 Does `-p` read stdin?

| # | command | result |
|---|---|---|
| A | `printf 'Reply with the single word: alpha' \| copilot -p - --allow-all-tools --no-auto-update -s` | `No task provided yet. What would you like me to help with?` — `-` is taken as the literal prompt text, **stdin ignored** |
| B | `printf 'Reply with the single word: bravo' \| copilot -p "" --allow-all-tools --no-auto-update -s` | `bravo` — **stdin is read** |

`-p` with no operand at all (`copilot -p --allow-all-tools …`) answered
`I'm ready to help. What would you like me to work on?` and did not read stdin either. **`-p ""`
— `-p` present, operand empty — is the form that works.** `-p` still has to be there: it is what
puts the CLI in non-interactive mode at all.

### 2.3 Does a multi-line prompt arrive whole?

```
printf 'line1: ignore\n\nline2: the word is "zeppelin"\n\nline3: how many lines does this prompt have? reply with exactly: <count> <word>\n' \
  | copilot -p "" --allow-all-tools --no-auto-update --output-format json
```

Final `assistant.message`: **`"3 zeppelin"`**. Three non-blank lines counted, blank lines and
double quotes survived, exit code 0, `premiumRequests: 1`.

### 2.4 Is there an `@file` form?

`copilot -p "@/tmp/keelprobe2.txt" --allow-all-tools --output-format json < /dev/null` did answer
with the file's contents (`delta`) — but the JSONL shows **why**:

```json
"toolRequests": [{"name": "bash",
                  "arguments": {"command": "cat /tmp/keelprobe2.txt 2>&1 | head -200",
                                "description": "View referenced file"}}]
```

The CLI passed `@path` to the model as **literal text**, and the model shelled out to `cat`. There
is no `@file` expansion. With `bash` excluded — which is how this executor always runs (C-1) —
that path delivers nothing at all. **A temp-file transport is not available on this CLI.**

### 2.5 The Claude side, for comparison

`ClaudeCodeExecutor` has always used stdin: `_build_argv` ends at `-p` with no operand and
`subprocess.run(..., input=prompt)` supplies the text. So one rule now covers both hosts.

## 3. The transport chosen

**The prompt is written to the child's stdin. No argv element carries any of it, on any OS.**

* `CopilotExecutor._build_argv` now emits `-p ""`; the prompt is gone from argv entirely.
* Both executors call one shared helper, `_run_with_prompt_on_stdin` in `keel_runtime/executor.py`,
  which is the single place either prompt is handed to a child process.
* The prompt is written as **UTF-8 bytes**, not through `subprocess`'s `text=True`. `text=True`
  translates `\n` to `\r\n` on Windows and encodes in the machine's locale encoding (`cp1252` on a
  stock Windows), which would mangle any non-ASCII character a stranger typed. stdout and stderr
  are decoded back explicitly, UTF-8, `errors="replace"`.
* stdin is a pipe, so `cmd.exe` never parses it: there is nothing left to truncate, quote or
  expand, and the nonce fence survives verbatim everywhere.

**C-2 is restated as:** *the prompt reaches the CLI on stdin as UTF-8 bytes, never as an argv
element and never as a shell string.* `COPILOT_MAX_PROMPT_BYTES` (512 KiB) stays at the same
number, no longer as an `ARG_MAX` guard but as a runaway guard — refusing by name beats spending a
five-minute timeout and a model call.

## 4. What this proves, and what it does not

**Proved, on this Mac (macOS, logged-in Copilot, isolated `COPILOT_HOME`, 2026-09-10):** one real
`CopilotExecutor.execute` through the new transport, with a nine-line founder text carrying five
`LINE-*` lines and a magic word on the fifth, returned

```json
{"outcome": "COMPLETED", "result": {"summary": "5 lines, magic word ZEPPELIN"}}
```

`num_turns: 1`, `premium_requests: 1`, `exit_code: 0`, `total_cost_usd` absent (C-7). One request.

**Not proved: Windows against the real CLI.** This repository holds no `COPILOT_GITHUB_TOKEN`, so
the model-driven acceptance job cannot run anywhere. `.github/workflows/acceptance.yml`'s
`model-driven` job is now a three-OS matrix and carries a step that, when that secret exists, sends
a three-line prompt through `CopilotExecutor` on each OS and asserts the model counted three lines
and echoed the word that only appears on the third. Until the secret is added, the Windows
evidence is the fake-CLI suite: all seven previously-skipped tests now run on Windows CI through
the `.cmd` shim from PR #1, including one whose prompt is forty lines of blank lines, quotes,
backslashes and flag-shaped text and which compares what the CLI read off stdin with the rendered
prompt **character for character**.

## 5. A separate finding, recorded not fixed

`_copilot_final_answer` selects the `assistant.message` whose `data.phase == "final_answer"`. On
2026-09-10, CLI 1.0.83 emits that marker on a **`gpt-5.6-luna`** reply and **not** on a
**`claude-sonnet-5`** one — the same command, the same flags, only `--model` differing:

```
copilot -p "" --model gpt-5.6-luna     ... -> phase = final_answer
copilot -p "" --model claude-sonnet-5  ... -> phase = None
```

An unpinned run whose router picks `claude-sonnet-5` therefore fails with
`executor produced no final_answer message` even though the model answered correctly. This is
unrelated to the transport and is left for its own change; it is a fresh argument for C-5's
`KEEL_COPILOT_MODEL` pinning, which is what the macOS proof and the new acceptance step both use.
