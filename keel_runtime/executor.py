"""Executor abstraction: turns a job's request_payload into a structured response.

The runtime owns no workflow, project, instruction, memory, or schema state (spec
FR-024) -- it only renders the request into a prompt and parses the answer back into
the outcome/questions/result shape `response_validator` expects. Ships one real
implementation, `ClaudeCodeExecutor`, which shells out to the `claude` CLI in
non-interactive print mode (spec FR-028).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .response_validator import InvalidResponse  # re-exported for executor callers

__all__ = [
    "InferenceRequest",
    "Executor",
    "ExecutorUnavailable",
    "ExecutorAuthFailure",
    "ExecutorTimeout",
    "InvalidResponse",
    "build_prompt",
    "ClaudeCodeExecutor",
    "get_executor",
]


class ExecutorUnavailable(Exception):
    """The configured executor could not run at all (missing binary, LLM unreachable)."""


class ExecutorAuthFailure(Exception):
    """The executor ran but reported an authentication/authorization failure."""


class ExecutorTimeout(Exception):
    """The executor did not answer within its configured timeout."""


@dataclass
class InferenceRequest:
    job_id: str
    interaction_id: str
    turn_number: int
    request_payload: dict


class Executor(ABC):
    @abstractmethod
    def execute(self, request: InferenceRequest) -> dict:
        """Return {outcome: ..., questions: [...]} or {outcome: ..., result: ...}."""


def build_prompt(request: InferenceRequest) -> str:
    """Renders the design's SYSTEM/CONTEXT/HISTORY/INPUT/RESPONSE-REQUIREMENTS prompt."""
    payload = request.request_payload
    instruction = payload.get("instruction", "")
    context = payload.get("context", {})
    history = payload.get("interaction_history", [])
    input_ = payload.get("input", {})
    response_contract = payload.get("response_contract", {})
    sections = [
        "SYSTEM",
        "You are Keel's local inference executor. Respond with a single JSON object "
        "only -- no prose before or after it.",
        "",
        "CONTEXT",
        json.dumps(context, indent=2),
        "",
        "HISTORY",
        json.dumps(history, indent=2),
        "",
        "INPUT",
        json.dumps(input_, indent=2),
        "",
        "INSTRUCTION",
        instruction,
        "",
        "RESPONSE-REQUIREMENTS",
        json.dumps(response_contract, indent=2),
    ]
    return "\n".join(sections)


class ClaudeCodeExecutor(Executor):
    """Invokes the `claude` CLI in non-interactive print mode (`claude -p <prompt>`)."""

    def __init__(self, binary: str = "claude", timeout_seconds: float = 120.0):
        self.binary = binary
        self.timeout_seconds = timeout_seconds

    def execute(self, request: InferenceRequest) -> dict:
        if shutil.which(self.binary) is None:
            raise ExecutorUnavailable(f"'{self.binary}' executable not found on PATH")

        prompt = build_prompt(request)
        try:
            completed = subprocess.run(
                [self.binary, "-p", prompt],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExecutorTimeout(
                f"'{self.binary}' did not respond within {self.timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise ExecutorUnavailable(str(exc)) from exc

        if completed.returncode != 0:
            combined = f"{completed.stdout}\n{completed.stderr}".lower()
            if "auth" in combined or "login" in combined or "unauthorized" in combined:
                raise ExecutorAuthFailure(completed.stderr.strip() or "authentication failed")
            raise ExecutorUnavailable(
                completed.stderr.strip() or f"'{self.binary}' exited {completed.returncode}"
            )

        return _extract_json(completed.stdout)


def _extract_json(text: str) -> dict:
    """Extracts the first complete top-level JSON object found anywhere in `text`."""
    start = text.find("{")
    if start == -1:
        raise InvalidResponse("no JSON object found in executor output")
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:index + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise InvalidResponse(
                        f"could not parse executor output as JSON: {exc}"
                    ) from exc
    raise InvalidResponse("no complete JSON object found in executor output")


_EXECUTORS = {
    "claude-code": lambda: ClaudeCodeExecutor(),
}


def get_executor(name: str) -> Executor:
    if name == "stub":
        # Lazy import: keel_runtime.testing is a test-only dependency of the package,
        # never loaded on a real `--executor claude-code` run.
        from .testing.stub_executor import StubExecutor

        return StubExecutor()

    factory = _EXECUTORS.get(name)
    if factory is None:
        known = ", ".join(sorted(list(_EXECUTORS.keys()) + ["stub"]))
        raise SystemExit(f"unknown executor '{name}'; known executors: {known}")
    return factory()
