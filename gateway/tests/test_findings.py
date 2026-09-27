"""Policy seam through the specialist envelope, with Google as the fake boundary."""
import copy
import unittest

from gateway.interceptor import intercept, annotate_response
from specialist_envelope import build_diagnostic_envelope

CONTRACT = {"spreadsheet_id": "fixture-sheet", "operations": ["get-metadata", "get-values"],
            "tabs": {"Performance": {"columns": {"A": "date", "B": "revenue"}}},
            "limits": {"max_rows": 10, "max_columns": 2, "max_cells": 20}}


class PolicyGateway:
    def __init__(self):
        self.google_calls = []

    def __call__(self, operation, arguments):
        event = {"interceptorInputVersion": "1.0", "mcp": {"gatewayRequest": {"body": {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "SheetsRead___" + operation, "arguments": arguments}}}}}
        decision = intercept(event, CONTRACT)["mcp"]
        if "transformedGatewayRequest" not in decision:
            raise ValueError("Rejected before Google")
        self.google_calls.append(decision["transformedGatewayRequest"])
        data = ({"values": [["2026-01-15", 125.5]]} if operation == "get-values" else {
            "sheets": [{"data": [{"startRow": 0, "startColumn": 0,
                                  "rowData": [{"values": [{"formattedValue": "Date"},
                                                           {"formattedValue": "Revenue"}]}]}]}]})
        event["mcp"]["gatewayResponse"] = {"statusCode": 200, "body": {
            "jsonrpc": "2.0", "id": 1, "result": {"structuredContent": data}}}
        return annotate_response(event, CONTRACT)["mcp"]["transformedGatewayResponse"]["body"]["result"]["structuredContent"]


def request(operation="get-values", range_value="Performance!A2:B2"):
    return {"task_id": "t", "context_id": "c", "objective": "Inspect revenue",
            "scope": {"metric": "revenue", "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                      "read": {"operation": operation, "arguments": {
                          "spreadsheetId": "fixture-sheet",
                          "ranges" if operation == "get-metadata" else "range": range_value}}}}


class FindingsTests(unittest.TestCase):
    def test_within_contract_read_becomes_semantic_finding(self):
        gateway = PolicyGateway()
        envelope = build_diagnostic_envelope(request(), gateway)
        self.assertEqual("complete", envelope["status"])
        finding = envelope["findings"][0]
        self.assertEqual("revenue", finding["metric"])
        self.assertEqual(125.5, finding["value"])
        self.assertEqual("'Performance'!B2", finding["basis"])
        self.assertEqual(1, len(gateway.google_calls))

    def test_metadata_discovery_has_a_source_and_no_business_value_claim(self):
        envelope = build_diagnostic_envelope(request("get-metadata", "Performance!A1:B1"), PolicyGateway())
        self.assertEqual("complete", envelope["status"])
        finding = envelope["findings"][0]
        self.assertEqual("revenue", finding["metric"])
        self.assertEqual("'Performance'!B1", finding["basis"])
        self.assertIn("header", finding["claim"])
        self.assertIn("not a business metric value", " ".join(finding["assumptions"]))

    def test_disallowed_requests_fail_envelope_without_google(self):
        for operation, range_value in [("get-values", "Private!A2:B2"),
                                       ("get-values", "Performance!A2:C2"),
                                       ("get-values", "Performance!A1:B11"),
                                       ("update", "Performance!A2:B2")]:
            gateway = PolicyGateway()
            envelope = build_diagnostic_envelope(request(operation, range_value), gateway)
            self.assertEqual("failed", envelope["status"])
            self.assertEqual([], envelope["findings"])
            self.assertEqual([], gateway.google_calls)
