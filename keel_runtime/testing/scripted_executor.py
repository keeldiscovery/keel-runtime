"""ScriptedExecutor -- deterministic, test-only Executor driven by a script file (spec
`001-scripted-executor` FR-001).

Selected with `--executor scripted`, never a default. The script is a JSON object
`{screen: [entries...]}`; each screen's entries are consumed in order, one per call to
`execute`, repeating the last entry once exhausted -- per screen, per process (a
restarted runtime starts the script over). The screen is never LLM-derived: it is
inferred from the request payload's own `context` keys, per keel-cloud spec
`022-inference-orchestrator` FR-010's table exactly.
"""
from __future__ import annotations

import copy

from ..executor import Executor, ExecutorUnavailable, InferenceRequest

_FIXED_KEY_SCREENS = {
    frozenset({"project_name"}): "PROBLEM_FRAME",
    frozenset({"problem_statement", "existing_roles"}): "PROBLEM_ASSUMPTIONS",
    frozenset({"project_name", "problem_statement", "existing_roles"}): "SOLUTION_FRAME",
    frozenset(
        {"solution_statement", "problem_statement", "existing_roles"}
    ): "SOLUTION_ASSUMPTIONS",
    frozenset(
        {"project_name", "problem_statement", "solution_statement", "existing_roles"}
    ): "COMMERCIAL_FRAME",
    frozenset(
        {
            "commercial_statement",
            "problem_statement",
            "solution_statement",
            "existing_roles",
        }
    ): "COMMERCIAL_ASSUMPTIONS",
}


def infer_screen(context: dict) -> str:
    """spec 022 FR-010's context-key table, implemented exactly and nothing looser."""
    keys = frozenset(context.keys())

    fixed = _FIXED_KEY_SCREENS.get(keys)
    if fixed is not None:
        return fixed
    if "current_statement" in context:
        return "COMMERCIAL_REFRAME" if "solution_statement" in context else "SOLUTION_REFRAME"
    if "invitation_id" in context:
        return "INTERPRET"
    if "deal_breakers" in context:
        return "BRIEF"

    raise ExecutorUnavailable(
        f"scripted executor cannot infer a screen from context keys {sorted(context.keys())}"
    )


class ScriptedExecutor(Executor):
    def __init__(self, script: dict):
        if not isinstance(script, dict):
            raise ExecutorUnavailable("scripted executor script must be a JSON object")
        # `_source` (and any other underscore-prefixed key) is metadata, not a screen.
        self._script = {
            screen: entries for screen, entries in script.items() if not screen.startswith("_")
        }
        self._cursors: dict[str, int] = {}

    def execute(self, request: InferenceRequest) -> dict:
        context = request.request_payload.get("context", {})
        screen = infer_screen(context)

        entries = self._script.get(screen)
        if not entries:
            raise ExecutorUnavailable(f"scripted executor has no entry for {screen}")

        index = self._cursors.get(screen, 0)
        entry = entries[min(index, len(entries) - 1)]
        self._cursors[screen] = index + 1

        response = copy.deepcopy(entry)
        if screen == "INTERPRET" and response.get("outcome") == "COMPLETED":
            response["result"] = _resolve_interpret_result(response["result"], context)
        return response


def _resolve_interpret_result(result: dict, context: dict) -> dict:
    """Fills `invitationId` from the context (spec 022 FR-016 refuses otherwise) and
    resolves each `perAnswer[].assumptionId` from the assumption *heading* the script
    writes to the real id, via the context's `assumptions[]` (`{id, heading, statement}`).
    """
    result["invitationId"] = context.get("invitation_id")

    heading_to_id = {
        assumption["heading"]: assumption["id"] for assumption in context.get("assumptions", [])
    }
    for answer in result.get("perAnswer", []):
        heading = answer["assumptionId"]
        resolved_id = heading_to_id.get(heading)
        if resolved_id is None:
            raise ExecutorUnavailable(
                f"scripted executor cannot resolve assumption heading '{heading}' to an id"
            )
        answer["assumptionId"] = resolved_id

    return result
