"""Local fallback for the credential-free Data Gateway math target."""
from __future__ import annotations

from math import sqrt
from statistics import median
from typing import Any, Iterable, Mapping

APPROVED_OPERATIONS = frozenset({"sum", "average", "percent_change", "group_by_aggregate", "median", "stddev", "variance", "correlation", "min_max", "top_n"})


class MathPolicyDenied(ValueError):
    pass


def run_math(operation: str, rows: Iterable[Mapping[str, Any]], field: str, **options: Any) -> Any:
    """Pure computation over rows already returned by the Sheets-read target."""
    if operation not in APPROVED_OPERATIONS:
        raise MathPolicyDenied("Math operation is not approved.")
    materialized = list(rows)
    values = [float(row[field]) for row in materialized if isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool)]
    if not values:
        raise ValueError("Math operation requires numeric rows.")
    if operation == "sum": return float(sum(values))
    if operation == "average": return float(sum(values) / len(values))
    if operation == "percent_change":
        if len(values) < 2 or values[0] == 0: raise ValueError("percent_change requires a non-zero first value and a later value.")
        return float((values[-1] - values[0]) / values[0] * 100)
    if operation == "median": return float(median(values))
    if operation in {"variance", "stddev"}:
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return float(variance if operation == "variance" else sqrt(variance))
    if operation == "min_max": return {"min": float(min(values)), "max": float(max(values))}
    if operation == "top_n":
        count = options.get("n", 1)
        if not isinstance(count, int) or count < 1: raise ValueError("top_n requires a positive integer n.")
        return [float(value) for value in sorted(values, reverse=True)[:count]]
    if operation == "correlation":
        other = options.get("other_field")
        pairs = [(float(row[field]), float(row[other])) for row in materialized if isinstance(other, str) and isinstance(row.get(field), (int, float)) and isinstance(row.get(other), (int, float))]
        if len(pairs) < 2: raise ValueError("correlation requires two numeric fields and two rows.")
        left, right = zip(*pairs); left_mean, right_mean = sum(left) / len(left), sum(right) / len(right)
        denominator = sqrt(sum((v - left_mean) ** 2 for v in left) * sum((v - right_mean) ** 2 for v in right))
        if denominator == 0: raise ValueError("correlation requires varying values.")
        return float(sum((x - left_mean) * (y - right_mean) for x, y in pairs) / denominator)
    if operation == "group_by_aggregate":
        group_field = options.get("group_field")
        if not isinstance(group_field, str): raise ValueError("group_by_aggregate requires group_field.")
        groups: dict[str, float] = {}
        for row in materialized:
            if isinstance(row.get(group_field), str) and isinstance(row.get(field), (int, float)):
                groups[row[group_field]] = groups.get(row[group_field], 0.0) + float(row[field])
        return groups
    raise MathPolicyDenied("Math operation is not implemented.")
