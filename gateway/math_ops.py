"""Credential-free math target for data already returned by SheetsRead."""
from __future__ import annotations

from math import sqrt
from statistics import median
from typing import Any, Iterable, Mapping


APPROVED_OPERATIONS = frozenset({
    "sum", "average", "percent_change", "group_by_aggregate", "median",
    "stddev", "variance", "correlation", "min_max", "top_n",
})


class MathPolicyDenied(ValueError):
    """The requested calculation is outside the data contract."""


def run_math(operation: str, rows: Iterable[Mapping[str, Any]], field: str, **options: Any) -> Any:
    """Compute an approved operation from caller-supplied rows only.

    This module intentionally has no network or credential dependency; the
    Sheets-read gateway remains the only component that can contact Google.
    """
    if operation not in APPROVED_OPERATIONS:
        raise MathPolicyDenied("Math operation is not approved.")
    values = [float(row[field]) for row in rows
              if isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool)]
    if not values:
        raise ValueError("Math operation requires numeric rows.")
    if operation == "sum":
        return float(sum(values))
    if operation == "average":
        return float(sum(values) / len(values))
    if operation == "percent_change":
        if len(values) < 2 or values[0] == 0:
            raise ValueError("percent_change requires a non-zero first value and a later value.")
        return float((values[-1] - values[0]) / values[0] * 100)
    if operation == "median":
        return float(median(values))
    if operation == "variance":
        mean = sum(values) / len(values)
        return float(sum((value - mean) ** 2 for value in values) / len(values))
    if operation == "stddev":
        mean = sum(values) / len(values)
        return float(sqrt(sum((value - mean) ** 2 for value in values) / len(values)))
    if operation == "min_max":
        return {"min": float(min(values)), "max": float(max(values))}
    if operation == "top_n":
        count = options.get("n", 1)
        if not isinstance(count, int) or count < 1:
            raise ValueError("top_n requires a positive integer n.")
        return [float(value) for value in sorted(values, reverse=True)[:count]]
    if operation == "correlation":
        other = options.get("other_field")
        pairs = [(float(row[field]), float(row[other])) for row in rows
                 if isinstance(other, str) and isinstance(row.get(field), (int, float))
                 and isinstance(row.get(other), (int, float))]
        if len(pairs) < 2:
            raise ValueError("correlation requires two numeric fields and two rows.")
        left, right = zip(*pairs)
        left_mean, right_mean = sum(left) / len(left), sum(right) / len(right)
        denominator = sqrt(sum((v - left_mean) ** 2 for v in left) * sum((v - right_mean) ** 2 for v in right))
        if denominator == 0:
            raise ValueError("correlation requires varying values.")
        return float(sum((x - left_mean) * (y - right_mean) for x, y in pairs) / denominator)
    if operation == "group_by_aggregate":
        group_field = options.get("group_field")
        if not isinstance(group_field, str):
            raise ValueError("group_by_aggregate requires group_field.")
        groups: dict[str, float] = {}
        for row in rows:
            if isinstance(row.get(group_field), str) and isinstance(row.get(field), (int, float)):
                groups[row[group_field]] = groups.get(row[group_field], 0.0) + float(row[field])
        return groups
    raise MathPolicyDenied("Math operation is not implemented.")


def handler(event: Mapping[str, Any], _context: Any = None) -> dict[str, Any]:
    """Lambda entrypoint; the Gateway supplies the selected tool as operation."""
    operation = event.get("operation") or event.get("tool_name") or event.get("name")
    rows, field = event.get("rows"), event.get("field")
    if not isinstance(operation, str) or not isinstance(rows, list) or not isinstance(field, str):
        raise MathPolicyDenied("MathOps requires operation, rows, and field.")
    return {"value": run_math(operation, rows, field, **{key: value for key, value in event.items()
                                                           if key not in {"operation", "tool_name", "name", "rows", "field"}})}
