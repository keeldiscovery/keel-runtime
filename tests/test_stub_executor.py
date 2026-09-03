"""Tests for the deterministic StubExecutor (spec FR-028)."""
import unittest

from keel_runtime.executor import ExecutorUnavailable, InferenceRequest
from keel_runtime.testing.stub_executor import StubExecutor


def _request(content, turn_number=1):
    return InferenceRequest(
        job_id="job-1",
        interaction_id="interaction-1",
        turn_number=turn_number,
        request_payload={"input": {"content": content}},
    )


class StubExecutorTest(unittest.TestCase):
    def setUp(self):
        self.executor = StubExecutor()

    def test_ask_returns_needs_input_with_q1(self):
        response = self.executor.execute(_request("ask"))
        self.assertEqual(response["outcome"], "NEEDS_INPUT")
        self.assertEqual(len(response["questions"]), 1)
        question = response["questions"][0]
        self.assertEqual(question["id"], "q1")
        self.assertEqual(question["question"], "What would you like echoed?")
        self.assertEqual(question["input_type"], "text")
        self.assertTrue(question["required"])

    def test_crash_raises_executor_unavailable(self):
        with self.assertRaises(ExecutorUnavailable):
            self.executor.execute(_request("crash"))

    def test_garbage_returns_a_result_that_fails_validation_downstream(self):
        response = self.executor.execute(_request("garbage"))
        self.assertEqual(response, {"outcome": "COMPLETED", "result": {"unexpected": True}})

    def test_anything_else_echoes_with_the_jobs_turn_number(self):
        response = self.executor.execute(_request("hello keel", turn_number=3))
        self.assertEqual(
            response,
            {"outcome": "COMPLETED", "result": {"echo": "hello keel", "turn_number": 3}},
        )

    def test_after_ask_style_content_is_treated_as_the_default_branch(self):
        response = self.executor.execute(_request("after ask", turn_number=2))
        self.assertEqual(
            response,
            {"outcome": "COMPLETED", "result": {"echo": "after ask", "turn_number": 2}},
        )


if __name__ == "__main__":
    unittest.main()
