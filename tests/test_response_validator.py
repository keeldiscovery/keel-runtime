"""Tests for keel_runtime.response_validator (mirrors spec FR-019)."""
import unittest

from keel_runtime.response_validator import InvalidResponse, validate_response

# The exact contract SC-002 uses for the echo job.
SC002_CONTRACT = {
    "allowed_outcomes": ["NEEDS_INPUT", "COMPLETED"],
    "completed_result_schema": {
        "type": "object",
        "required": ["echo", "turn_number"],
        "properties": {"echo": {"type": "string"}, "turn_number": {"type": "integer"}},
    },
}


class ResponseValidatorTest(unittest.TestCase):
    def test_completed_result_matching_schema_passes(self):
        validate_response(
            {"outcome": "COMPLETED", "result": {"echo": "hi", "turn_number": 1}},
            SC002_CONTRACT,
        )  # must not raise

    def test_needs_input_with_a_well_formed_question_passes(self):
        response = {
            "outcome": "NEEDS_INPUT",
            "questions": [
                {"id": "q1", "question": "?", "input_type": "text", "required": True}
            ],
        }
        validate_response(response, SC002_CONTRACT)  # must not raise

    def test_stub_garbage_result_fails_the_sc002_schema(self):
        with self.assertRaises(InvalidResponse):
            validate_response(
                {"outcome": "COMPLETED", "result": {"unexpected": True}}, SC002_CONTRACT
            )

    def test_outcome_not_in_allowed_outcomes_fails(self):
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {"type": "object"},
        }
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "NEEDS_INPUT", "questions": []}, contract)

    def test_needs_input_requires_non_empty_questions(self):
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "NEEDS_INPUT", "questions": []}, SC002_CONTRACT)

    def test_needs_input_question_missing_a_field_fails(self):
        response = {
            "outcome": "NEEDS_INPUT",
            "questions": [{"id": "q1", "question": "?", "input_type": "text"}],
        }
        with self.assertRaises(InvalidResponse):
            validate_response(response, SC002_CONTRACT)

    def test_required_keyword(self):
        schema = {"type": "object", "required": ["a"]}
        contract = {"allowed_outcomes": ["COMPLETED"], "completed_result_schema": schema}
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "COMPLETED", "result": {}}, contract)
        validate_response({"outcome": "COMPLETED", "result": {"a": 1}}, contract)  # passes

    def test_type_keyword(self):
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {"type": "string"},
        }
        validate_response({"outcome": "COMPLETED", "result": "ok"}, contract)  # passes
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "COMPLETED", "result": 5}, contract)

    def test_integer_type_rejects_bool(self):
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {"type": "integer"},
        }
        validate_response({"outcome": "COMPLETED", "result": 3}, contract)  # passes
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "COMPLETED", "result": True}, contract)

    def test_enum_keyword(self):
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {"enum": ["a", "b"]},
        }
        validate_response({"outcome": "COMPLETED", "result": "a"}, contract)  # passes
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "COMPLETED", "result": "c"}, contract)

    def test_items_keyword(self):
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {"type": "array", "items": {"type": "integer"}},
        }
        validate_response({"outcome": "COMPLETED", "result": [1, 2, 3]}, contract)  # passes
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "COMPLETED", "result": [1, "x"]}, contract)

    def test_additional_properties_false(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        }
        contract = {"allowed_outcomes": ["COMPLETED"], "completed_result_schema": schema}
        validate_response({"outcome": "COMPLETED", "result": {"a": "x"}}, contract)  # passes
        with self.assertRaises(InvalidResponse):
            validate_response(
                {"outcome": "COMPLETED", "result": {"a": "x", "b": "y"}}, contract
            )

    def test_unknown_keyword_is_ignored(self):
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {"type": "string", "format": "email"},
        }
        validate_response({"outcome": "COMPLETED", "result": "not-an-email"}, contract)

    # -- spec 002-words-are-words FR-006 ---------------------------------------------

    def test_max_length_keyword(self):
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {"type": "string", "maxLength": 5},
        }
        validate_response({"outcome": "COMPLETED", "result": "hello"}, contract)  # passes
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "COMPLETED", "result": "hello!"}, contract)

    def test_min_length_keyword(self):
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {"type": "string", "minLength": 3},
        }
        validate_response({"outcome": "COMPLETED", "result": "abc"}, contract)  # passes
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "COMPLETED", "result": "ab"}, contract)

    def test_max_items_keyword(self):
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {"type": "array", "maxItems": 2, "items": {"type": "string"}},
        }
        validate_response({"outcome": "COMPLETED", "result": ["a", "b"]}, contract)  # passes
        with self.assertRaises(InvalidResponse):
            validate_response({"outcome": "COMPLETED", "result": ["a", "b", "c"]}, contract)

    def test_pattern_keyword_uses_re_search(self):
        # design §L3: no bare http(s)/www links in agent words.
        contract = {
            "allowed_outcomes": ["COMPLETED"],
            "completed_result_schema": {
                "type": "string",
                "pattern": r"^(?!.*(https?://|www\.))",
            },
        }
        validate_response({"outcome": "COMPLETED", "result": "a plain sentence"}, contract)
        with self.assertRaises(InvalidResponse):
            validate_response(
                {"outcome": "COMPLETED", "result": "visit https://example.com"}, contract
            )

    def test_nested_field_caps_apply(self):
        schema = {
            "type": "object",
            "required": ["statement"],
            "properties": {"statement": {"type": "string", "maxLength": 5}},
        }
        contract = {"allowed_outcomes": ["COMPLETED"], "completed_result_schema": schema}
        validate_response({"outcome": "COMPLETED", "result": {"statement": "short"}}, contract)
        with self.assertRaises(InvalidResponse):
            validate_response(
                {"outcome": "COMPLETED", "result": {"statement": "too long"}}, contract
            )


if __name__ == "__main__":
    unittest.main()
