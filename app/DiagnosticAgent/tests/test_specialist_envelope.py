import json
import unittest

from specialist_envelope import build_diagnostic_envelope


class DiagnosticEnvelopeTests(unittest.TestCase):
    def test_complete_response_has_a_schema_valid_finding(self) -> None:
        envelope = build_diagnostic_envelope(
            {
                "task_id": "task-001",
                "context_id": "investigation-001",
                "objective": "Investigate the revenue decline.",
                "scope": {
                    "metric": "revenue",
                    "segment": "enterprise",
                    "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                },
            }
        )

        self.assertEqual("complete", envelope["status"])
        self.assertEqual(1, len(envelope["findings"]))
        finding = envelope["findings"][0]
        self.assertEqual("revenue", finding["metric"])
        self.assertEqual("enterprise", finding["segment"])
        self.assertEqual(
            {"start": "2026-01-01", "end": "2026-01-31"}, finding["time_range"]
        )
        self.assertIsInstance(finding["id"], str)
        self.assertEqual("Synthetic diagnostic signal for revenue.", finding["claim"])
        self.assertIsInstance(finding["value"], float)
        self.assertGreaterEqual(finding["confidence"], 0)
        self.assertLessEqual(finding["confidence"], 1)
        self.assertIn("fake", finding["basis"].lower())
        self.assertEqual("fake-sheet://revenue/enterprise", finding["source_pointer"])
        self.assertTrue(finding["assumptions"])
        self.assertEqual([], envelope["clarifying_questions"])

    def test_incomplete_first_pass_requests_clarification(self) -> None:
        envelope = build_diagnostic_envelope(
            {
                "task_id": "task-001",
                "context_id": "investigation-001",
                "objective": "Investigate the revenue decline.",
                "scope": {"metric": "revenue"},
            }
        )

        self.assertEqual("needs_clarification", envelope["status"])
        self.assertEqual([], envelope["findings"])
        self.assertTrue(envelope["clarifying_questions"])

    def test_confirmed_incomplete_request_is_partial(self) -> None:
        envelope = build_diagnostic_envelope(
            {
                "task_id": "task-001",
                "context_id": "investigation-001",
                "objective": "Investigate the revenue decline.",
                "scope": {"metric": "revenue"},
                "prior_context": {"continuation_confirmed": True},
            }
        )

        self.assertEqual("partial", envelope["status"])
        self.assertEqual([], envelope["clarifying_questions"])
        self.assertEqual(1, len(envelope["findings"]))
        self.assertTrue(
            any("time_range" in assumption for assumption in envelope["findings"][0]["assumptions"])
        )

    def test_missing_metric_requires_clarification_even_after_confirmation(self) -> None:
        envelope = build_diagnostic_envelope(
            {
                "task_id": "task-001",
                "context_id": "investigation-001",
                "objective": "Investigate the decline.",
                "scope": {"time_range": {"start": "2026-01-01", "end": "2026-01-31"}},
                "prior_context": {"continuation_confirmed": True},
            }
        )

        self.assertEqual("needs_clarification", envelope["status"])
        self.assertEqual([], envelope["findings"])

    def test_missing_scope_is_malformed(self) -> None:
        envelope = build_diagnostic_envelope(
            {
                "task_id": "task-001",
                "context_id": "investigation-001",
                "objective": "Investigate the revenue decline.",
            }
        )

        self.assertEqual("failed", envelope["status"])

    def test_malformed_request_returns_a_failed_envelope(self) -> None:
        envelope = build_diagnostic_envelope(
            {
                "task_id": "task-001",
                "context_id": "investigation-001",
                "objective": "Investigate the revenue decline.",
                "scope": {
                    "metric": "revenue",
                    "time_range": {"start": "not-a-date", "end": "2026-01-31"},
                },
            }
        )

        self.assertEqual("failed", envelope["status"])

    def test_identical_requests_produce_the_same_id_and_nullable_segment(self) -> None:
        request = {
            "task_id": "task-001",
            "context_id": "investigation-001",
            "objective": "Investigate the revenue decline.",
            "scope": {
                "metric": "revenue",
                "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
            },
        }

        first = build_diagnostic_envelope(request)
        second = build_diagnostic_envelope(request)

        self.assertEqual(first["findings"][0]["id"], second["findings"][0]["id"])
        self.assertIsNone(first["findings"][0]["segment"])

    def test_final_artifact_is_one_json_envelope(self) -> None:
        envelope = build_diagnostic_envelope(
            {
                "task_id": "task-001",
                "context_id": "investigation-001",
                "objective": "Investigate the revenue decline.",
                "scope": {
                    "metric": "revenue",
                    "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                },
            }
        )

        encoded = json.dumps(envelope)
        self.assertEqual(envelope, json.loads(encoded))

    def test_missing_a2a_identifiers_returns_a_failed_envelope(self) -> None:
        envelope = build_diagnostic_envelope(
            {
                "objective": "Investigate the revenue decline.",
                "scope": {
                    "metric": "revenue",
                    "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                },
            }
        )

        self.assertEqual("failed", envelope["status"])


if __name__ == "__main__":
    unittest.main()
