import unittest

from lambda_function import handler


class EvaluatorTests(unittest.TestCase):
    def test_boundary_compares_actual_trace_with_scenario_assertion(self):
        result = handler({"evaluator_name": "DataBoundaryViolation", "assertions": {"data_boundary": {"expected_decision": "deny"}}, "trace": {"data_boundary_decision": "deny"}}, None)
        self.assertEqual("PASS", result["result"])

    def test_gating_reports_a_mismatch_without_a_threshold(self):
        result = handler({"evaluator_name": "BestEffortConfirmationGating", "assertions": {"best_effort_confirmation": {"expected_needs_clarification": True}}, "trace": {"needs_clarification": False}}, None)
        self.assertEqual("FAIL", result["result"])
