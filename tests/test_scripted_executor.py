"""Tests for the deterministic ScriptedExecutor (spec 001-scripted-executor, as amended by
its `AMENDMENT-measured-beliefs.md`).

The table is no longer transcribed here either. Every inference test is driven from the same
`context-keys.json` the executor loads, so this file asserts that the executor *implements
keel-cloud's export* rather than that it agrees with a second hand-written copy -- which is the
exact failure the amendment exists to end.
"""
import json
import tempfile
import unittest
from pathlib import Path

from keel_runtime.executor import ExecutorUnavailable, InferenceRequest
from keel_runtime.response_validator import validate_response
from keel_runtime.testing.scripted_executor import (
    DEFAULT_CONTEXT_KEYS_PATH,
    ScriptedExecutor,
    infer_screen,
    load_screen_table,
)

FIXTURES = Path(__file__).parent / "fixtures"
DEFAULT_SCRIPT_PATH = (
    Path(__file__).parent.parent
    / "keel_runtime"
    / "testing"
    / "scripts"
    / "countly-problem.json"
)

# The four vocabulary names the measured-beliefs model retired. None of them may appear
# anywhere in the bundled script or in any contract this repo vendors.
RETIRED_KEYS = ("claimType", "stance", "perAnswer", "assumptionId", "evidence")


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


def _exported_keys():
    """keel-cloud's own `context-keys.json`, as bundled -- `{screen: [key, ...]}`."""
    return {
        screen: keys
        for screen, keys in _load(DEFAULT_CONTEXT_KEYS_PATH).items()
        if not screen.startswith("_")
    }


def _context_for(keys):
    """A context with exactly those keys. Values are irrelevant to inference by design:
    keel-cloud writes every key for its screen, `null` where it has no value, which is what
    makes an exact key-set match the right rule."""
    return {key: None for key in keys}


class ScreenTableTest(unittest.TestCase):
    """The table is loaded, not written (RT-001)."""

    def test_bundled_table_loads_and_carries_every_exported_screen(self):
        table = load_screen_table()
        self.assertEqual(sorted(table.values()), sorted(_exported_keys()))

    def test_bundled_table_carries_the_screens_the_old_hand_written_one_never_had(self):
        # The whole reason for the amendment: `market` on every framing screen,
        # `founder_name` on the three assumption screens, `claims` on BRIEF, and three
        # correction key sets nothing had heard of.
        exported = _exported_keys()
        self.assertIn("market", exported["PROBLEM_FRAME"])
        self.assertIn("founder_name", exported["PROBLEM_ASSUMPTIONS"])
        self.assertIn("claims", exported["BRIEF"])
        self.assertNotIn("deal_breakers", exported["BRIEF"])
        self.assertIn("anchors", exported["INTERPRET"])
        self.assertNotIn("assumptions", exported["INTERPRET"])
        for stage in ("PROBLEM", "SOLUTION", "COMMERCIAL"):
            self.assertIn(f"{stage}_ASSUMPTIONS.correction", exported)

    def test_every_exported_key_set_is_distinct(self):
        exported = _exported_keys()
        sets = [frozenset(keys) for keys in exported.values()]
        self.assertEqual(len(set(sets)), len(sets),
                         "two screens share a key set; exact-match inference is not honest")

    def test_a_table_naming_two_screens_with_one_key_set_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context-keys.json"
            path.write_text(json.dumps({"A": ["x", "y"], "B": ["y", "x"]}))
            with self.assertRaises(ExecutorUnavailable) as ctx:
                load_screen_table(path)
            self.assertIn("same context key set", str(ctx.exception))

    def test_a_missing_table_is_refused_naming_the_path(self):
        with self.assertRaises(ExecutorUnavailable) as ctx:
            load_screen_table("/nowhere/context-keys.json")
        self.assertIn("/nowhere/context-keys.json", str(ctx.exception))

    def test_a_table_that_is_not_json_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context-keys.json"
            path.write_text("not json at all")
            with self.assertRaises(ExecutorUnavailable):
                load_screen_table(path)

    def test_metadata_keys_are_not_screens(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context-keys.json"
            path.write_text(json.dumps({"_source": "somewhere", "PROBLEM_FRAME": ["a"]}))
            self.assertEqual(load_screen_table(path), {frozenset({"a"}): "PROBLEM_FRAME"})


class InferScreenTest(unittest.TestCase):
    """RT-001: the current table, exactly, driven from the export itself."""

    def test_every_exported_screen_is_inferred_from_its_own_key_set(self):
        for screen, keys in _exported_keys().items():
            with self.subTest(screen=screen):
                self.assertEqual(infer_screen(_context_for(keys)), screen)

    def test_unknown_key_set_raises_naming_the_keys(self):
        with self.assertRaises(ExecutorUnavailable) as ctx:
            infer_screen({"mystery_key": 1})
        self.assertIn("mystery_key", str(ctx.exception))

    def test_the_old_hand_written_key_sets_now_miss(self):
        """The regression this amendment is about, asserted as a regression.

        Each of these was a row of the retired table. Every one of them is now a key set
        keel-cloud never writes, and every one must raise rather than answer a screen.
        """
        stale = [
            {"project_name": None},                                           # no market
            {"problem_statement": None, "existing_roles": None},              # no market/founder_name
            {"project_name": None, "problem_statement": None, "existing_roles": None},
            {"deal_breakers": None},                                          # BRIEF, retired
            {"invitation_id": None, "assumptions": None},                     # INTERPRET, retired
        ]
        for context in stale:
            with self.subTest(keys=sorted(context)):
                with self.assertRaises(ExecutorUnavailable):
                    infer_screen(context)

    def test_a_superset_of_a_known_key_set_is_not_that_screen(self):
        """Strictness, kept on purpose (spec judgement call 6): an extra key keel-cloud has
        started writing must be a refusal that names it, not a screen answered anyway."""
        keys = list(_exported_keys()["PROBLEM_FRAME"]) + ["something_new"]
        with self.assertRaises(ExecutorUnavailable) as ctx:
            infer_screen(_context_for(keys))
        self.assertIn("something_new", str(ctx.exception))

    def test_an_operator_supplied_table_overrides_the_bundled_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context-keys.json"
            path.write_text(json.dumps({"MADE_UP_SCREEN": ["only_key"]}))
            table = load_screen_table(path)
            self.assertEqual(infer_screen({"only_key": 1}, table), "MADE_UP_SCREEN")
            with self.assertRaises(ExecutorUnavailable):
                infer_screen(_context_for(_exported_keys()["PROBLEM_FRAME"]), table)


class ScriptedExecutorAcceptanceTest(unittest.TestCase):
    """Spec §Acceptance Scenarios 1-3, restated against the current table (RT-006)."""

    def setUp(self):
        exported = _exported_keys()
        self.problem_frame = _context_for(exported["PROBLEM_FRAME"])
        self.solution_frame = _context_for(exported["SOLUTION_FRAME"])

    def test_scenario_1_problem_frame_first_entry(self):
        script = {
            "PROBLEM_FRAME": [
                {"outcome": "COMPLETED", "result": {"statement": "first"}},
                {"outcome": "COMPLETED", "result": {"statement": "second"}},
            ]
        }
        executor = ScriptedExecutor(script)
        response = executor.execute(_request(self.problem_frame))
        self.assertEqual(response, {"outcome": "COMPLETED", "result": {"statement": "first"}})

    def test_scenario_2_needs_input_then_next_entry_on_turn_two(self):
        script = {
            "PROBLEM_FRAME": [
                {
                    "outcome": "NEEDS_INPUT",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "which delivery did you mean?",
                            "input_type": "text",
                            "required": True,
                        }
                    ],
                },
                {"outcome": "COMPLETED", "result": {"statement": "the statement"}},
            ]
        }
        executor = ScriptedExecutor(script)
        first = executor.execute(_request(self.problem_frame))
        self.assertEqual(first["outcome"], "NEEDS_INPUT")
        self.assertEqual(first, script["PROBLEM_FRAME"][0])

        second = executor.execute(
            _request(
                self.problem_frame,
                interaction_history=[{"role": "user", "content": "the late one"}],
                turn_number=2,
            )
        )
        self.assertEqual(second, script["PROBLEM_FRAME"][1])

    def test_scenario_3_missing_screen_raises_executor_unavailable_naming_it(self):
        executor = ScriptedExecutor({})
        with self.assertRaises(ExecutorUnavailable) as ctx:
            executor.execute(_request(self.problem_frame))
        self.assertIn("PROBLEM_FRAME", str(ctx.exception))

    def test_exhaustion_repeats_the_last_entry(self):
        script = {"PROBLEM_FRAME": [{"outcome": "COMPLETED", "result": {"statement": "only"}}]}
        executor = ScriptedExecutor(script)
        executor.execute(_request(self.problem_frame))
        second = executor.execute(_request(self.problem_frame))
        third = executor.execute(_request(self.problem_frame))
        self.assertEqual(second, {"outcome": "COMPLETED", "result": {"statement": "only"}})
        self.assertEqual(third, {"outcome": "COMPLETED", "result": {"statement": "only"}})

    def test_cursors_are_independent_per_screen(self):
        script = {
            "PROBLEM_FRAME": [{"outcome": "COMPLETED", "result": {"statement": "p"}}],
            "SOLUTION_FRAME": [{"outcome": "COMPLETED", "result": {"statement": "s"}}],
        }
        executor = ScriptedExecutor(script)
        problem = executor.execute(_request(self.problem_frame))
        solution = executor.execute(_request(self.solution_frame))
        self.assertEqual(problem["result"]["statement"], "p")
        self.assertEqual(solution["result"]["statement"], "s")

    def test_a_correction_screen_is_a_screen_like_any_other(self):
        keys = _exported_keys()["PROBLEM_ASSUMPTIONS.correction"]
        script = {
            "PROBLEM_ASSUMPTIONS.correction": [
                {"outcome": "COMPLETED", "result": {"reply": "redone", "changes": []}}
            ]
        }
        executor = ScriptedExecutor(script)
        response = executor.execute(_request(_context_for(keys)))
        self.assertEqual(response["result"]["reply"], "redone")


class InterpretResolutionTest(unittest.TestCase):
    """RT-002: invitationId is filled; anchorId passes through, checked against `anchors[]`."""

    def _context(self):
        return {
            "invitation_id": "invitation-42",
            "anchors": [
                {"anchor_id": "A1", "prompt": "Tell us what happened.",
                 "text": "The crates were two short.", "tap": None},
                {"anchor_id": "A2", "prompt": "And the one before?",
                 "text": "Last month, same supplier.", "tap": None},
            ],
        }

    def _executor(self, anchorings):
        return ScriptedExecutor({
            "INTERPRET": [{
                "outcome": "COMPLETED",
                "result": {"anchorings": anchorings, "unprompted": [], "flags": []},
            }]
        })

    def test_invitation_id_is_filled_from_context(self):
        executor = self._executor([{"anchorId": "A1", "anchoring": "ANCHORED"}])
        response = executor.execute(_request(self._context()))
        self.assertEqual(response["result"]["invitationId"], "invitation-42")

    def test_anchor_id_passes_through_unchanged(self):
        executor = self._executor([
            {"anchorId": "A1", "anchoring": "ANCHORED"},
            {"anchorId": "A2", "anchoring": "GUESSED"},
        ])
        response = executor.execute(_request(self._context()))
        self.assertEqual(
            [a["anchorId"] for a in response["result"]["anchorings"]], ["A1", "A2"])
        self.assertEqual(
            [a["anchoring"] for a in response["result"]["anchorings"]], ["ANCHORED", "GUESSED"])

    def test_an_anchor_the_context_does_not_carry_is_refused_naming_it(self):
        executor = self._executor([{"anchorId": "A9", "anchoring": "ANCHORED"}])
        with self.assertRaises(ExecutorUnavailable) as ctx:
            executor.execute(_request(self._context()))
        self.assertIn("A9", str(ctx.exception))

    def test_a_blank_anchor_is_not_in_the_context_and_so_cannot_be_answered(self):
        """`ScreenContextBuilder.anchorsWritten` omits a blank answer entirely. A script that
        answers one is answering something the reader was never shown."""
        context = self._context()
        context["anchors"] = [context["anchors"][0]]
        executor = self._executor([
            {"anchorId": "A1", "anchoring": "ANCHORED"},
            {"anchorId": "A2", "anchoring": "GUESSED"},
        ])
        with self.assertRaises(ExecutorUnavailable) as ctx:
            executor.execute(_request(context))
        self.assertIn("A2", str(ctx.exception))

    def test_the_source_entry_is_not_mutated_between_calls(self):
        executor = self._executor([{"anchorId": "A1", "anchoring": "ANCHORED"}])
        first = executor.execute(_request(self._context()))
        second = executor.execute(_request(self._context()))
        self.assertEqual(first["result"]["anchorings"], second["result"]["anchorings"])


class BundledScriptContractValidityTest(unittest.TestCase):
    """RT-003/RT-004: the bundled script is one corpus stage, in the current shapes, and it
    validates against keel-cloud's own exported contracts.
    """

    @classmethod
    def setUpClass(cls):
        cls.contracts = _load(FIXTURES / "response_contracts.json")
        cls.script = _load(DEFAULT_SCRIPT_PATH)
        cls.keys = _exported_keys()

    def test_it_is_the_problem_stage_of_the_frozen_corpus_and_says_so(self):
        self.assertIn("01-countly", self.script["_source"])
        self.assertEqual(
            {k for k in self.script if not k.startswith("_")},
            {"PROBLEM_FRAME", "PROBLEM_ASSUMPTIONS", "INTERPRET"},
        )

    def test_it_names_the_keel_cloud_commit_its_shapes_came_from(self):
        self.assertTrue(self.script["_keel_cloud_commit"])
        self.assertIn("generate_bundled_script.py", self.script["_generated_by"])

    def test_every_screen_exercised_once_validates_against_its_contract(self):
        for screen in ("PROBLEM_FRAME", "PROBLEM_ASSUMPTIONS", "INTERPRET"):
            with self.subTest(screen=screen):
                executor = ScriptedExecutor(self.script)
                context = _context_for(self.keys[screen])
                if screen == "INTERPRET":
                    context = {
                        "invitation_id": "invitation-1",
                        "anchors": [{"anchor_id": "A1", "prompt": "p", "text": "t", "tap": None}],
                    }
                response = executor.execute(_request(context))
                validate_response(response, self.contracts[screen])

    def test_it_carries_no_retired_vocabulary(self):
        blob = json.dumps(self.script)
        for retired in RETIRED_KEYS:
            with self.subTest(key=retired):
                self.assertNotIn(f'"{retired}"', blob)

    def test_the_assumptions_entry_carries_the_whole_envelope(self):
        result = self.script["PROBLEM_ASSUMPTIONS"][0]["result"]
        self.assertEqual(
            sorted(result), ["assumptions", "normalization_rationale", "questionnaire"])
        self.assertEqual(sorted(result["questionnaire"]), ["anchors", "introduction"])
        for assumption in result["assumptions"]:
            self.assertIn("expectation", assumption)
            self.assertIn(assumption["expectation"]["type"], ("INTERVAL", "CHOICE"))
            self.assertTrue({"new", "reuse"} & set(assumption["role"]))

    def test_the_role_is_introduced_once_and_reused_after(self):
        assumptions = self.script["PROBLEM_ASSUMPTIONS"][0]["result"]["assumptions"]
        introductions = [a for a in assumptions if "new" in a["role"]]
        self.assertEqual(len(introductions), 1, "one role, introduced exactly once")
        self.assertTrue(all("reuse" in a["role"] for a in assumptions[1:]))

    def test_every_interpret_entry_answers_only_anchors_it_was_shown(self):
        anchor_ids = {
            anchor["id"]
            for anchor in self.script["PROBLEM_ASSUMPTIONS"][0]["result"]["questionnaire"]["anchors"]
        }
        for index, entry in enumerate(self.script["INTERPRET"]):
            with self.subTest(entry=index):
                self.assertEqual(entry["outcome"], "COMPLETED")
                for anchoring in entry["result"]["anchorings"]:
                    self.assertIn(anchoring["anchorId"], anchor_ids)
                    self.assertIn(anchoring["anchoring"], ("ANCHORED", "GUESSED"))

    def test_interpret_never_needs_input(self):
        """The reading contract allows COMPLETED and nothing else (vendored fact V8)."""
        self.assertEqual(self.contracts["INTERPRET"]["allowed_outcomes"], ["COMPLETED"])
        for entry in self.script["INTERPRET"]:
            self.assertEqual(entry["outcome"], "COMPLETED")


class VendoredContractsTest(unittest.TestCase):
    """The fixture contracts are keel-cloud's export, not a hand-copy that can rot."""

    def test_the_fixture_names_the_export_it_came_from(self):
        contracts = _load(FIXTURES / "response_contracts.json")
        self.assertIn("screenContracts", contracts["_source"])
        self.assertEqual(
            sorted(k for k in contracts if not k.startswith("_")),
            sorted(_exported_keys()),
        )

    def test_no_contract_carries_retired_vocabulary(self):
        blob = json.dumps(_load(FIXTURES / "response_contracts.json"))
        for retired in RETIRED_KEYS:
            with self.subTest(key=retired):
                self.assertNotIn(f'"{retired}"', blob)


if __name__ == "__main__":
    unittest.main()
