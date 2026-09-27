"""Credential-free policy shared by the gateway interceptor and offline tests."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping


class PolicyDenied(ValueError):
    """A request exceeds the version-controlled data contract."""


def column_number(column: str) -> int:
    number = 0
    for character in column:
        number = number * 26 + ord(character) - ord("A") + 1
    return number


class SheetsPolicy:
    def __init__(self, contract: Mapping[str, Any]):
        self.contract = deepcopy(dict(contract))

    def authorize(self, operation: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        contract = self.contract
        if operation not in {"get-metadata", "get-values"} or operation not in contract["operations"]:
            raise PolicyDenied("Operation is not approved.")
        if set(arguments) != {"spreadsheetId", "range"}:
            raise PolicyDenied("Only spreadsheetId and range are accepted.")
        if arguments["spreadsheetId"] != contract["spreadsheet_id"]:
            raise PolicyDenied("Spreadsheet is not approved.")
        value = arguments["range"]
        match = re.fullmatch(
            r"(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_ ]*))!([A-Z]{1,3})([1-9][0-9]{0,6})(?::([A-Z]{1,3})([1-9][0-9]{0,6}))?",
            value if isinstance(value, str) else "",
        )
        if match is None:
            raise PolicyDenied("Use one explicit, bounded A1 range with a tab name.")
        quoted, plain, first_column, first_row, last_column, last_row = match.groups()
        tab = quoted.replace("''", "'") if quoted is not None else plain
        if tab not in contract["tabs"]:
            raise PolicyDenied("Tab is not approved.")
        last_column = last_column or first_column
        last_row = last_row or first_row
        start, end = column_number(first_column), column_number(last_column)
        row_start, row_end = int(first_row), int(last_row)
        rows, columns = row_end - row_start + 1, end - start + 1
        limits = contract["limits"]
        if (rows < 1 or columns < 1 or rows > limits["max_rows"]
                or columns > limits["max_columns"] or rows * columns > limits["max_cells"]):
            raise PolicyDenied("Range exceeds the per-call limits or is reversed.")
        fields = {column: semantic for column, semantic in contract["tabs"][tab]["columns"].items()
                  if start <= column_number(column) <= end}
        if len(fields) != columns:
            raise PolicyDenied("Range contains an unapproved column.")
        if operation == "get-metadata" and (row_start != 1 or row_end != 1):
            raise PolicyDenied("Metadata discovery is limited to the header row.")
        escaped_tab = tab.replace("'", "''")
        return {"spreadsheet_id": contract["spreadsheet_id"], "tab": tab,
                "range": f"'{escaped_tab}'!{first_column}{first_row}:{last_column}{last_row}",
                "fields": fields}
