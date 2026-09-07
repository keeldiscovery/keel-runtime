"""Tests for `tools/generate_bundled_script.py`'s `brief_for` (DRIFT #42, keel-e2e-eval
`runs/DRIFT.md`, and spec `001-scripted-executor`'s `AMENDMENT-measured-beliefs.md`).

The bundled scripted-executor script carried no `BRIEF` entry, so every reading run off it
failed the job keel-cloud's spec 030 starts automatically after a reading, to write
`Overview.whatThisSays`. `brief_for` composes that one entry deterministically from a corpus
entry's own `expected.stages` verdicts -- never a model's words, never hand-written -- and
refuses rather than exceeding keel-cloud's own contract (`ScreenResponseContracts.briefSchema`,
vendored at `tests/fixtures/response_contracts.json`'s `BRIEF`): non-blank, at most 1200 code
points, no link.
"""
from __future__ import annotations

import unittest
from unittest import mock

from tools.generate_bundled_script import (
    BRIEF_MAX_CODEPOINTS,
    BRIEF_VERDICT_SENTENCE,
    Refusal,
    brief_for,
)


def _entry(stages, entry_id="test-entry"):
    return {"id": entry_id, "expected": {"stages": stages}}


class BriefForTest(unittest.TestCase):
    def test_result_shape_is_one_completed_brief_entry(self):
        result = brief_for(_entry({"PROBLEM": "SUPPORTED"}))
        self.assertEqual(list(result), ["BRIEF"])
        self.assertEqual(len(result["BRIEF"]), 1)
        entry = result["BRIEF"][0]
        self.assertEqual(entry["outcome"], "COMPLETED")
        self.assertEqual(list(entry["result"]), ["whatThisSays"])

    def test_first_sentence_marks_it_as_scripted(self):
        says = brief_for(_entry({"PROBLEM": "MIXED"}))["BRIEF"][0]["result"]["whatThisSays"]
        self.assertTrue(says.startswith("This is a scripted reading"))

    def test_one_sentence_per_stage_present_in_expected_stages(self):
        says = brief_for(_entry({
            "PROBLEM": "CONTRADICTED", "SOLUTION": "MIXED", "COMMERCIAL": "SUPPORTED",
        }))["BRIEF"][0]["result"]["whatThisSays"]
        self.assertIn("problem claim was contradicted", says.lower())
        self.assertIn("solution claim came back mixed", says.lower())
        self.assertIn("commercial claim held up", says.lower())

    def test_stage_order_is_fixed_regardless_of_dict_order(self):
        forward = brief_for(_entry(
            {"PROBLEM": "SUPPORTED", "SOLUTION": "MIXED", "COMMERCIAL": "CONTRADICTED"}))
        backward = brief_for(_entry(
            {"COMMERCIAL": "CONTRADICTED", "SOLUTION": "MIXED", "PROBLEM": "SUPPORTED"}))
        self.assertEqual(forward, backward)

    def test_is_deterministic(self):
        entry = _entry({"PROBLEM": "MIXED", "SOLUTION": "SUPPORTED", "COMMERCIAL": "MIXED"})
        self.assertEqual(brief_for(entry), brief_for(entry))

    def test_a_stage_missing_from_expected_stages_is_skipped_not_invented(self):
        says = brief_for(_entry({"PROBLEM": "SUPPORTED"}))["BRIEF"][0]["result"]["whatThisSays"]
        self.assertNotIn("solution", says.lower())
        self.assertNotIn("commercial", says.lower())

    def test_no_expected_stages_is_a_refusal_naming_the_entry(self):
        with self.assertRaises(Refusal) as ctx:
            brief_for({"id": "bare-entry", "expected": {}})
        self.assertIn("bare-entry", str(ctx.exception))

    def test_a_verdict_outside_the_table_is_a_refusal_naming_it(self):
        with self.assertRaises(Refusal) as ctx:
            brief_for(_entry({"PROBLEM": "UNTESTED"}))
        self.assertIn("UNTESTED", str(ctx.exception))
        self.assertIn("PROBLEM", str(ctx.exception))

    def test_a_paragraph_over_the_cap_is_refused_not_truncated(self):
        oversized = {"SUPPORTED": "x" * (BRIEF_MAX_CODEPOINTS + 1)}
        with mock.patch.dict(BRIEF_VERDICT_SENTENCE, oversized, clear=True):
            with self.assertRaises(Refusal) as ctx:
                brief_for(_entry({"PROBLEM": "SUPPORTED"}))
        self.assertIn("over the", str(ctx.exception))

    def test_a_sentence_carrying_a_link_is_refused(self):
        linking = {"SUPPORTED": "see https://example.com/{stage} for more."}
        with mock.patch.dict(BRIEF_VERDICT_SENTENCE, linking, clear=True):
            with self.assertRaises(Refusal) as ctx:
                brief_for(_entry({"PROBLEM": "SUPPORTED"}))
        self.assertIn("link", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
