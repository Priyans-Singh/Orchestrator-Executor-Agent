"""The gateway request policy decides access before any upstream invocation."""
import unittest
import json
from pathlib import Path

from gateway.policy import SheetsPolicy


CONTRACT = {
    "spreadsheet_id": "fixture-sheet",
    "operations": ["get-metadata", "get-values"],
    "tabs": {"Performance": {"columns": {"A": "date", "B": "revenue", "D": "orders"}}},
    "limits": {"max_rows": 100, "max_columns": 3, "max_cells": 200},
}


class PolicyTests(unittest.TestCase):
    def test_packaged_contract_matches_the_reviewed_source_of_truth(self):
        root = Path(__file__).parents[2]
        self.assertEqual(
            json.loads((root / "docs/data-contract.yaml").read_text()),
            json.loads((root / "gateway/data-contract.yaml").read_text()),
        )

    def test_accepts_only_approved_bounded_read_and_attaches_semantics(self):
        approved = SheetsPolicy(CONTRACT).authorize("get-values", {
            "spreadsheetId": "fixture-sheet", "range": "Performance!A2:B10"})
        self.assertEqual("'Performance'!A2:B10", approved["range"])
        self.assertEqual({"A": "date", "B": "revenue"}, approved["fields"])
        self.assertEqual("fixture-sheet", approved["spreadsheet_id"])


if __name__ == "__main__":
    unittest.main()
