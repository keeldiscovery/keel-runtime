"""Tests for the deterministic ScriptedExecutor (spec 001-scripted-executor)."""
import json
import unittest
from pathlib import Path

from keel_runtime.executor import ExecutorUnavailable, InferenceRequest
from keel_runtime.response_validator import validate_response
from keel_runtime.testing.scripted_executor import ScriptedExecutor, infer_screen

FIXTURES = Path(__file__).parent / "fixtures"
DEFAULT_SCRIPT_PATH = (
    Path(__file__).parent.parent
    / "keel_runtime"
    / "testing"
    / "scripts"
    / "payroll-exceptions.json"
)


def _request(context, interaction_history=None, turn_number=1):
    return InferenceRequest(
        job_id="job-1",
        interaction_id="interaction-1",
        turn_number=turn_number,
        request_payload={
            "context": context,
            "interaction_history": interaction_history or [],
        },
    )


def _load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class InferScreenTest(unittest.TestCase):
    """Spec §Edge Cases: the context-key table, exhaustively."""

    def test_project_name_only_is_problem_frame(self):
        self.assertEqual(infer_screen({"project_name": "Acme"}), "PROBLEM_FRAME")

    def test_problem_statement_and_roles_is_problem_assumptions(self):
        self.assertEqual(
            infer_screen({"problem_statement": "s", "existing_roles": []}),
            "PROBLEM_ASSUMPTIONS",
        )

    def test_project_problem_roles_is_solution_frame(self):
        self.assertEqual(
            infer_screen(
                {"project_name": "Acme", "problem_statement": "s", "existing_roles": []}
            ),
            "SOLUTION_FRAME",
        )

    def test_solution_problem_roles_is_solution_assumptions(self):
        self.assertEqual(
            infer_screen(
                {"solution_statement": "s", "problem_statement": "p", "existing_roles": []}
            ),
            "SOLUTION_ASSUMPTIONS",
        )

    def test_project_problem_solution_roles_is_commercial_frame(self):
        self.assertEqual(
            infer_screen(
                {
                    "project_name": "Acme",
                    "problem_statement": "p",
                    "solution_statement": "s",
                    "existing_roles": [],
                }
            ),
            "COMMERCIAL_FRAME",
        )

    def test_commercial_problem_solution_roles_is_commercial_assumptions(self):
        self.assertEqual(
            infer_screen(
                {
                    "commercial_statement": "c",
                    "problem_statement": "p",
                    "solution_statement": "s",
                    "existing_roles": [],
                }
            ),
            "COMMERCIAL_ASSUMPTIONS",
        )

    def test_current_statement_without_solution_statement_is_solution_reframe(self):
        self.assertEqual(
            infer_screen({"current_statement": "c", "problem_statement": "p"}),
            "SOLUTION_REFRAME",
        )

    def test_current_statement_with_solution_statement_is_commercial_reframe(self):
        self.assertEqual(
            infer_screen(
                {
                    "current_statement": "c",
                    "problem_statement": "p",
                    "solution_statement": "s",
                }
            ),
            "COMMERCIAL_REFRAME",
        )

    def test_invitation_id_present_is_interpret(self):
        self.assertEqual(infer_screen({"invitation_id": "inv-1"}), "INTERPRET")

    def test_deal_breakers_present_is_brief(self):
        self.assertEqual(infer_screen({"deal_breakers": []}), "BRIEF")

    def test_unknown_key_set_raises_naming_the_keys(self):
        with self.assertRaises(ExecutorUnavailable) as ctx:
            infer_screen({"mystery_key": 1})
        self.assertIn("mystery_key", str(ctx.exception))


class ScriptedExecutorAcceptanceTest(unittest.TestCase):
    """Spec §Acceptance Scenarios 1-3."""

    def test_scenario_1_problem_frame_first_entry(self):
        script = {
            "PROBLEM_FRAME": [
                {"outcome": "COMPLETED", "result": {"statement": "first"}},
                {"outcome": "COMPLETED", "result": {"statement": "second"}},
            ]
        }
        executor = ScriptedExecutor(script)
        response = executor.execute(_request({"project_name": "Acme"}))
        self.assertEqual(response, {"outcome": "COMPLETED", "result": {"statement": "first"}})

    def test_scenario_2_needs_input_then_next_entry_on_turn_two(self):
        script = {
            "PROBLEM_FRAME": [
                {
                    "outcome": "NEEDS_INPUT",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "hours or minutes?",
                            "input_type": "text",
                            "required": True,
                        }
                    ],
                },
                {"outcome": "COMPLETED", "result": {"statement": "the statement"}},
            ]
        }
        executor = ScriptedExecutor(script)
        first = executor.execute(_request({"project_name": "Acme"}))
        self.assertEqual(first["outcome"], "NEEDS_INPUT")
        self.assertEqual(first, script["PROBLEM_FRAME"][0])

        second = executor.execute(
            _request(
                {"project_name": "Acme"},
                interaction_history=[{"role": "user", "content": "hours"}],
                turn_number=2,
            )
        )
        self.assertEqual(second, script["PROBLEM_FRAME"][1])

    def test_scenario_3_missing_screen_raises_executor_unavailable_naming_it(self):
        executor = ScriptedExecutor({})
        with self.assertRaises(ExecutorUnavailable) as ctx:
            executor.execute(_request({"project_name": "Acme"}))
        self.assertIn("PROBLEM_FRAME", str(ctx.exception))

    def test_exhaustion_repeats_the_last_entry(self):
        script = {
            "PROBLEM_FRAME": [
                {"outcome": "COMPLETED", "result": {"statement": "only"}},
            ]
        }
        executor = ScriptedExecutor(script)
        executor.execute(_request({"project_name": "Acme"}))
        second = executor.execute(_request({"project_name": "Acme"}))
        third = executor.execute(_request({"project_name": "Acme"}))
        self.assertEqual(second, {"outcome": "COMPLETED", "result": {"statement": "only"}})
        self.assertEqual(third, {"outcome": "COMPLETED", "result": {"statement": "only"}})

    def test_cursors_are_independent_per_screen(self):
        script = {
            "PROBLEM_FRAME": [{"outcome": "COMPLETED", "result": {"statement": "p"}}],
            "SOLUTION_FRAME": [{"outcome": "COMPLETED", "result": {"statement": "s"}}],
        }
        executor = ScriptedExecutor(script)
        problem = executor.execute(_request({"project_name": "Acme"}))
        solution = executor.execute(
            _request(
                {
                    "project_name": "Acme",
                    "problem_statement": "p",
                    "existing_roles": [],
                }
            )
        )
        self.assertEqual(problem["result"]["statement"], "p")
        self.assertEqual(solution["result"]["statement"], "s")


class InterpretResolutionTest(unittest.TestCase):
    """Spec §Edge Cases: invitationId fill and heading -> assumptionId resolution."""

    def _context(self):
        return {
            "invitation_id": "invitation-42",
            "raw_answer_text": "...",
            "questions_asked": [],
            "assumptions": [
                {"id": "assumption-1", "heading": "Hours, not minutes", "statement": "..."},
                {"id": "assumption-2", "heading": "Someone owns it", "statement": "..."},
            ],
        }

    def test_invitation_id_is_filled_from_context(self):
        script = {
            "INTERPRET": [
                {
                    "outcome": "COMPLETED",
                    "result": {
                        "perAnswer": [
                            {
                                "assumptionId": "Hours, not minutes",
                                "evidence": [
                                    {
                                        "statement": "It's the hours.",
                                        "claimType": "PAST_BEHAVIOR",
                                        "stance": "SUPPORTS",
                                    }
                                ],
                            }
                        ]
                    },
                }
            ]
        }
        executor = ScriptedExecutor(script)
        response = executor.execute(_request(self._context()))
        self.assertEqual(response["result"]["invitationId"], "invitation-42")

    def test_heading_resolves_to_assumption_id(self):
        script = {
            "INTERPRET": [
                {
                    "outcome": "COMPLETED",
                    "result": {
                        "perAnswer": [
                            {
                                "assumptionId": "Someone owns it",
                                "evidence": [
                                    {
                                        "statement": "No one owns it today.",
                                        "claimType": "CURRENT_WORKFLOW",
                                        "stance": "CONTRADICTS",
                                    }
                                ],
                            }
                        ]
                    },
                }
            ]
        }
        executor = ScriptedExecutor(script)
        response = executor.execute(_request(self._context()))
        self.assertEqual(response["result"]["perAnswer"][0]["assumptionId"], "assumption-2")

    def test_unresolvable_heading_raises_executor_unavailable(self):
        script = {
            "INTERPRET": [
                {
                    "outcome": "COMPLETED",
                    "result": {
                        "perAnswer": [
                            {"assumptionId": "Not a real heading", "evidence": []}
                        ]
                    },
                }
            ]
        }
        executor = ScriptedExecutor(script)
        with self.assertRaises(ExecutorUnavailable) as ctx:
            executor.execute(_request(self._context()))
        self.assertIn("Not a real heading", str(ctx.exception))

    def test_needs_input_interpret_entry_passes_through_untouched(self):
        script = {
            "INTERPRET": [
                {
                    "outcome": "NEEDS_INPUT",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "which assumption?",
                            "input_type": "text",
                            "required": True,
                        }
                    ],
                }
            ]
        }
        executor = ScriptedExecutor(script)
        response = executor.execute(_request(self._context()))
        self.assertEqual(response, script["INTERPRET"][0])


class BundledScriptContractValidityTest(unittest.TestCase):
    """Spec Acceptance Scenario 4 / FR-004: every screen's bundled entry validates
    against the corresponding contract copied from keel-cloud spec 022 FR-012.
    """

    @classmethod
    def setUpClass(cls):
        cls.contracts = _load(FIXTURES / "response_contracts.json")
        cls.script = _load(DEFAULT_SCRIPT_PATH)

    def _contexts(self):
        roles = [{"id": "role-1", "label": "a payroll manager", "roleType": "PRACTITIONER", "about": "..."}]
        assumptions = [
            {"id": "a-1", "heading": h, "statement": "...", "risk": "LOAD_BEARING", "verdict": "PEOPLE_DISAGREE"}
            for h in self._interpret_headings()
        ]
        return {
            "PROBLEM_FRAME": {"project_name": "Payroll Exceptions"},
            "PROBLEM_ASSUMPTIONS": {"problem_statement": "p", "existing_roles": roles},
            "SOLUTION_FRAME": {
                "project_name": "Payroll Exceptions",
                "problem_statement": "p",
                "existing_roles": roles,
            },
            "SOLUTION_ASSUMPTIONS": {
                "solution_statement": "s",
                "problem_statement": "p",
                "existing_roles": roles,
            },
            "COMMERCIAL_FRAME": {
                "project_name": "Payroll Exceptions",
                "problem_statement": "p",
                "solution_statement": "s",
                "existing_roles": roles,
            },
            "COMMERCIAL_ASSUMPTIONS": {
                "commercial_statement": "c",
                "problem_statement": "p",
                "solution_statement": "s",
                "existing_roles": roles,
            },
            "SOLUTION_REFRAME": {
                "current_statement": "s",
                "problem_statement": "p",
                "assumptions": [],
                "contradicted_evidence": [],
            },
            "COMMERCIAL_REFRAME": {
                "current_statement": "c",
                "problem_statement": "p",
                "solution_statement": "s",
                "assumptions": [],
                "contradicted_evidence": [],
            },
            "INTERPRET": {
                "invitation_id": "invitation-1",
                "raw_answer_text": "...",
                "questions_asked": [],
                "assumptions": assumptions,
            },
            "BRIEF": {
                "deal_breakers": [],
                "going_ahead_reasoning": None,
                "problem_statement": "p",
                "solution_statement": "s",
                "commercial_statement": "c",
            },
        }

    def _interpret_headings(self):
        headings = set()
        for entry in self.script.get("INTERPRET", []):
            if entry.get("outcome") != "COMPLETED":
                continue
            for answer in entry["result"].get("perAnswer", []):
                headings.add(answer["assumptionId"])
        return sorted(headings)

    def test_every_screen_exercised_once_validates_against_its_contract(self):
        contexts = self._contexts()
        for screen, context in contexts.items():
            with self.subTest(screen=screen):
                executor = ScriptedExecutor(self.script)
                response = executor.execute(_request(context))
                contract = self.contracts[screen]
                validate_response(response, contract)

    def test_bundled_script_covers_all_ten_screens(self):
        expected = {
            "PROBLEM_FRAME",
            "PROBLEM_ASSUMPTIONS",
            "SOLUTION_FRAME",
            "SOLUTION_ASSUMPTIONS",
            "SOLUTION_REFRAME",
            "COMMERCIAL_FRAME",
            "COMMERCIAL_ASSUMPTIONS",
            "COMMERCIAL_REFRAME",
            "INTERPRET",
            "BRIEF",
        }
        screens_present = {key for key in self.script.keys() if not key.startswith("_")}
        self.assertEqual(screens_present, expected)

    def test_problem_frame_first_entry_is_needs_input(self):
        self.assertEqual(self.script["PROBLEM_FRAME"][0]["outcome"], "NEEDS_INPUT")


if __name__ == "__main__":
    unittest.main()
