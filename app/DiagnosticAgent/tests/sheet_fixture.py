"""Offline external gateway response for specialist envelope tests."""
from copy import deepcopy

READ = {"operation": "get-values", "arguments": {
    "spreadsheetId": "fixture-sheet", "range": "Performance!A2:D2"}}
RESULT = {"operation": "get-values", "spreadsheet_id": "fixture-sheet", "tab": "Performance",
          "range": "'Performance'!A2:D2",
          "fields": {"A": "date", "B": "revenue", "C": "segment", "D": "orders"},
          "data": {"values": [["2026-01-15", 125.5, "enterprise", 4]]}}


def reader(operation, arguments):
    return deepcopy(RESULT)
