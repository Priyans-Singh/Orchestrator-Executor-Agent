import json
import unittest

from specialist_envelope import build_diagnostic_envelope as build_envelope
from sheet_fixture import READ, reader


def build_diagnostic_envelope(request):
    if isinstance(request.get("scope"), dict):
        request["scope"]["read"] = READ
    return build_envelope(request, reader)


class DiagnosticEnvelopeTests(unittest.TestCase):
    def test_over_cap_range_is_paged_then_aggregated_at_the_envelope_seam(self) -> None:
        calls = []

        def paged_reader(operation, arguments):
            calls.append((operation, arguments.copy()))
            start = int(arguments["range"].split("!", 1)[1].split(":")[0][1:])
            end = int(arguments["range"].split(":")[1][1:])
            return {
                "operation": operation, "spreadsheet_id": "fixture-sheet", "tab": "Performance",
                "range": "'Performance'!" + arguments["range"].split("!", 1)[1],
                "fields": {"A": "date", "B": "revenue", "C": "segment", "D": "orders"},
                "approved_semantics": ["date", "revenue", "segment", "orders"],
                "math_operations": ["average"],
                "data": {"values": [["2026-01-15", float(row), "enterprise", row]
                                    for row in range(start, end + 1)]},
            }

        paged_reader.limits = {"max_rows": 100, "max_columns": 4, "max_cells": 400}
        envelope = build_envelope({
            "task_id": "task-001", "context_id": "investigation-001",
            "objective": "Investigate revenue.",
            "scope": {"metric": "revenue", "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                      "read": {"operation": "get-values", "arguments": {
                          "spreadsheetId": "fixture-sheet", "range": "Performance!A2:D201"}},
                      "math": {"operation": "average"}},
        }, paged_reader)

        self.assertEqual("complete", envelope["status"])
        self.assertEqual([("get-values", {"spreadsheetId": "fixture-sheet", "range": "Performance!A2:D101"}),
                          ("get-values", {"spreadsheetId": "fixture-sheet", "range": "Performance!A102:D201"})], calls)
        self.assertEqual(101.5, envelope["findings"][0]["value"])
        self.assertIn("stitched 'Performance'!A2:D201", envelope["findings"][0]["basis"])
        self.assertIn("math average", envelope["findings"][0]["basis"])

    def test_gateway_confirmed_alias_is_recorded_without_expanding_semantics(self) -> None:
        alias_result = {
            **reader("get-values", READ["arguments"]),
            "approved_semantics": ["date", "revenue", "segment", "orders"],
            "header_mappings": {"B": {"header": "Net Revenue", "semantic": "revenue", "is_alias": True}},
        }
        envelope = build_envelope({
            "task_id": "task-001", "context_id": "investigation-001", "objective": "Investigate revenue.",
            "scope": {"metric": "revenue", "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                      "read": READ},
        }, lambda *_: alias_result)
        finding = envelope["findings"][0]
        self.assertEqual("revenue", finding["metric"])
        self.assertTrue(any("Net Revenue" in assumption for assumption in finding["assumptions"]))

    def test_gateway_cannot_expand_contract_with_a_new_semantic(self) -> None:
        expanded = {
            **reader("get-values", READ["arguments"]),
            "fields": {"A": "date", "B": "unapproved_metric", "C": "segment", "D": "orders"},
            "approved_semantics": ["date", "revenue", "segment", "orders"],
        }
        envelope = build_envelope({
            "task_id": "task-001", "context_id": "investigation-001", "objective": "Investigate it.",
            "scope": {"metric": "unapproved_metric", "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                      "read": READ},
        }, lambda *_: expanded)
        self.assertEqual("failed", envelope["status"])

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
        self.assertEqual("Observed revenue at 'Performance'!B2.", finding["claim"])
        self.assertIsInstance(finding["value"], float)
        self.assertGreaterEqual(finding["confidence"], 0)
        self.assertLessEqual(finding["confidence"], 1)
        self.assertEqual("'Performance'!B2", finding["basis"])
        self.assertEqual("sheet://fixture-sheet/'Performance'!B2", finding["source_pointer"])
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
