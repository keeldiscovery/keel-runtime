# Tasks: The executor can only answer

**Input**: [spec.md](spec.md) (FR-001..008, SC-001..003) and keel-cloud
`canon/designs/words-are-words-design.md` §L1, §L2, §4.

**Rules**: scripted and stub executors untouched; no wire change; standard library only (the
runtime's posture, spec 001 FR-009). Gate: `python3 -m unittest discover -s tests -t .`.

- [ ] T001 `config.py`: `budget_usd` (env `KEEL_JOB_BUDGET_USD`, default 0.25) and `max_turns`
      (`KEEL_JOB_MAX_TURNS`, default 2), file-config keys, tests in `tests/test_config.py` (FR-007).
- [ ] T002 `executor.py` `build_prompt`: sections, the fence, the nonce, `SYSTEM_PROMPT` (FR-004).
- [ ] T003 `executor.py` `ClaudeCodeExecutor`: the closed argv, stdin prompt, per-job cwd, env
      allow-list, envelope schema from the contract, envelope parsing and the three error mappings;
      delete `_extract_json` and the substring sniff (FR-001, FR-002, FR-003).
- [ ] T004 `poller.py`: `envelope.json` + `request.json` per job, prune to newest 50 on start,
      failure message rule (FR-005).
- [ ] T005 `response_validator.py`: `maxLength`/`minLength`/`maxItems`/`pattern` (FR-006);
      fixtures in `tests/fixtures/response_contracts.json` gain one capped field per screen.
- [ ] T006 `tests/test_executor.py` with the fake-`claude` recorder script; `tests/test_poller.py` (FR-008).
- [ ] T007 README: minimum CLI version, the closed shape, the job directory; one live probe run and
      its envelope summarised under Discovered (SC-003).
- [ ] T008 Gate green (SC-001); commit in the house style with the trailers; no push.

## Discovered

(Record here anything the code taught that the spec did not know.)
