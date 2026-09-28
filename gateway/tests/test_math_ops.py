"""Math target performs only approved pure computation over supplied rows."""
import os
import unittest

from gateway.math_ops import MathPolicyDenied, run_math


class MathOpsTests(unittest.TestCase):
    def test_average_uses_only_supplied_rows_and_needs_no_google_credentials(self):
        previous = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        try:
            result = run_math("average", [{"revenue": 100}, {"revenue": 200}], "revenue")
        finally:
            if previous is not None:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = previous
        self.assertEqual(150.0, result)

    def test_unapproved_math_operation_is_denied(self):
        with self.assertRaises(MathPolicyDenied):
            run_math("execute_sql", [{"revenue": 100}], "revenue")
