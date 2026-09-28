"""Schema-valid Diagnostic analyst envelopes at the specialist A2A seam."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from typing import Any, Mapping, Callable
from math import isfinite
import re


# This is validation metadata, not a local calculator. Math execution must
# always pass through the DataGateway MathOps target.
APPROVED_OPERATIONS = frozenset({
    "sum", "average", "percent_change", "group_by_aggregate", "median",
    "stddev", "variance", "correlation", "min_max", "top_n",
})


def build_diagnostic_envelope(request: Mapping[str, Any], reader: Callable | None = None) -> dict[str, Any]:
    """Return a deterministic Diagnostic envelope for one delegation request.

    Load-bearing fields come from a policy-gated gateway response.
    A caller may add a narrative, but consumers must never parse it.
    """
    try:
        normalized = _normalize_request(request)
    except ValueError as error:
        return failed_diagnostic_envelope(str(error))

    metric = normalized["metric"]
    time_range = normalized["time_range"]
    if metric is None:
        return _clarification_envelope(["Which metric should this investigation analyze?"])

    if time_range is None and not normalized["continuation_confirmed"]:
        return _clarification_envelope(
            ["What ISO-8601 start and end dates should define the investigation time range?"]
        )

    read = request["scope"].get("read")
    if read is None:
        return _clarification_envelope(["Which approved spreadsheet and bounded tab/range should I read?"])
    if (not isinstance(read, Mapping) or set(read) != {"operation", "arguments"}
            or read["operation"] not in {"get-metadata", "get-values"}
            or not isinstance(read["arguments"], dict)):
        return failed_diagnostic_envelope("Invalid Sheet read request.")
    try:
        if reader is None:
            raise ValueError("No Data Gateway is configured.")
        result = _read_with_pagination(reader, read["operation"], read["arguments"])
        findings = _sheet_findings(normalized, result)
    except Exception:
        return failed_diagnostic_envelope("The policy-gated Sheet read could not be completed.")
    if not findings:
        return _clarification_envelope(["The approved range contains no matching numeric observations; clarify the range or metric."])
    math = request["scope"].get("math")
    if math is not None:
        try:
            findings = _math_finding(normalized, result, findings, math, reader)
        except (TypeError, ValueError, KeyError):
            return failed_diagnostic_envelope("The requested math operation is not approved or could not be completed.")
    status = "complete" if time_range is not None else "partial"
    return {
        "status": status,
        "findings": findings,
        "clarifying_questions": [],
        "narrative": None,
    }


def _normalize_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise ValueError("Delegation request must be a JSON object.")

    task_id = _required_non_empty_string(request, "task_id")
    context_id = _required_non_empty_string(request, "context_id")
    objective = request.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("Delegation request requires a non-empty objective.")

    if "scope" not in request:
        raise ValueError("Delegation request requires a scope object.")
    scope = request["scope"]
    if not isinstance(scope, Mapping):
        raise ValueError("scope must be an object when supplied.")

    metric = _optional_non_empty_string(scope, "metric")
    segment = _optional_non_empty_string(scope, "segment")
    time_range = _normalize_time_range(scope.get("time_range"))

    prior_context = request.get("prior_context", {})
    if prior_context is None:
        prior_context = {}
    if not isinstance(prior_context, Mapping):
        raise ValueError("prior_context must be an object when supplied.")
    continuation_confirmed = prior_context.get("continuation_confirmed", False)
    if not isinstance(continuation_confirmed, bool):
        raise ValueError("prior_context.continuation_confirmed must be a boolean.")

    return {
        "task_id": task_id,
        "context_id": context_id,
        "objective": objective.strip(),
        "metric": metric,
        "segment": segment,
        "time_range": time_range,
        "continuation_confirmed": continuation_confirmed,
    }


def _optional_non_empty_string(scope: Mapping[str, Any], field: str) -> str | None:
    value = scope.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"scope.{field} must be a non-empty string when supplied.")
    return value.strip()


def _required_non_empty_string(values: Mapping[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Delegation request requires a non-empty {field}.")
    return value.strip()


def _normalize_time_range(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("scope.time_range must be an object when supplied.")

    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("scope.time_range requires string start and end dates.")
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as error:
        raise ValueError("scope.time_range dates must use ISO-8601 YYYY-MM-DD.") from error
    if end_date < start_date:
        raise ValueError("scope.time_range.end must not precede start.")
    return {"start": start_date.isoformat(), "end": end_date.isoformat()}


def _sheet_findings(scope: Mapping[str, Any], result: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = result["fields"]
    approved_semantics = result.get("approved_semantics", list(fields.values()))
    if (not isinstance(approved_semantics, list) or not all(isinstance(item, str) for item in approved_semantics)
            or any(semantic not in approved_semantics for semantic in fields.values())):
        raise ValueError("Gateway attempted to expand the data contract.")
    if scope["metric"] not in fields.values():
        raise ValueError("Metric is not in the approved columns.")
    match = re.search(r"!([A-Z]+)([0-9]+):([A-Z]+)([0-9]+)$", result["range"])
    if match is None:
        raise ValueError("Gateway response requires a bounded source range.")
    first_column, first_row, last_column, last_row = match.groups()

    def index(column: str) -> int:
        number = 0
        for char in column:
            number = number * 26 + ord(char) - ord("A") + 1
        return number

    offset = index(first_column)
    if result["operation"] == "get-metadata":
        column = next(column for column, semantic in fields.items() if semantic == scope["metric"])
        cell = result["range"].rsplit("!", 1)[0] + f"!{column}{first_row}"
        pointer = f"sheet://{result['spreadsheet_id']}/{cell}"
        digest = sha256((pointer + "|" + scope["metric"]).encode()).hexdigest()
        return [{
            "id": f"finding-{digest[:16]}",
            "claim": f"Approved header for {scope['metric']} is present at {cell}.",
            "metric": scope["metric"], "segment": None,
            "time_range": scope["time_range"] or {"start": None, "end": None},
            "value": 1.0, "basis": cell, "source_pointer": pointer,
            "confidence": 1.0,
            "assumptions": [
                "Header discovery confirms the approved semantic field; 1.0 is a presence marker, not a business metric value."
            ],
        }]
    rows = result["data"].get("values", [])
    if (not isinstance(rows, list) or len(rows) > int(last_row) - int(first_row) + 1
            or any(not isinstance(row, list) or len(row) > index(last_column) - offset + 1 for row in rows)):
        raise ValueError("Gateway returned data outside the requested range.")
    findings = []
    for row_offset, row in enumerate(rows):
        values = {semantic: row[index(column) - offset]
                  for column, semantic in fields.items() if index(column) - offset < len(row)}
        if scope["time_range"]:
            observed_date = date.fromisoformat(values["date"])
            if not (scope["time_range"]["start"] <= observed_date.isoformat() <= scope["time_range"]["end"]):
                continue
        if scope["segment"] is not None and values.get("segment") != scope["segment"]:
            continue
        value = values.get(scope["metric"])
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
            continue
        column = next(column for column, semantic in fields.items() if semantic == scope["metric"])
        cell = result["range"].rsplit("!", 1)[0] + f"!{column}{int(first_row) + row_offset}"
        pointer = f"sheet://{result['spreadsheet_id']}/{cell}"
        digest = sha256((pointer + "|" + scope["metric"]).encode()).hexdigest()
        assumptions = ["Direct cell observation; no aggregation or causal inference was performed."]
        header_mapping = result.get("header_mappings", {}).get(column, {})
        if isinstance(header_mapping, Mapping) and header_mapping.get("semantic") == scope["metric"] and header_mapping.get("is_alias") is True:
            header = header_mapping.get("header")
            if not isinstance(header, str) or not header:
                raise ValueError("Alias mapping is invalid.")
            assumptions.append(f"Header alias '{header}' was mapped to approved semantic field {scope['metric']}.")
        if scope["time_range"] is None:
            assumptions.append("time_range was not supplied; confirmed best-effort analysis.")
        findings.append({
            "id": f"finding-{digest[:16]}", "claim": f"Observed {scope['metric']} at {cell}.",
            "metric": scope["metric"], "segment": scope["segment"],
            "time_range": scope["time_range"] or {"start": None, "end": None},
            "value": float(value), "basis": cell, "source_pointer": pointer,
            "confidence": 1.0, "assumptions": assumptions,
        })
    return findings


def _read_with_pagination(reader: Callable, operation: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Split a legitimate oversized values range before it reaches the gateway."""
    if operation != "get-values":
        return reader(operation, dict(arguments))
    value = arguments.get("range")
    match = re.fullmatch(r"((?:'[^']*(?:''[^']*)*')|[A-Za-z_][A-Za-z0-9_ ]*)!([A-Z]+)([1-9][0-9]*):([A-Z]+)([1-9][0-9]*)", value if isinstance(value, str) else "")
    if match is None:
        return reader(operation, dict(arguments))
    tab, first_column, first_row, last_column, last_row = match.groups()
    columns = _column_number(last_column) - _column_number(first_column) + 1
    limits = getattr(reader, "limits", {"max_rows": 100, "max_columns": 4, "max_cells": 400})
    if not isinstance(limits, Mapping):
        raise ValueError("Data Gateway limits are unavailable.")
    max_rows = min(int(limits["max_rows"]), int(limits["max_cells"]) // columns)
    if columns > int(limits["max_columns"]) or max_rows < 1:
        return reader(operation, dict(arguments))
    start, end = int(first_row), int(last_row)
    results = []
    for page_start in range(start, end + 1, max_rows):
        page_end = min(end, page_start + max_rows - 1)
        page_arguments = {**arguments, "range": f"{tab}!{first_column}{page_start}:{last_column}{page_end}"}
        results.append(reader(operation, page_arguments))
    if len(results) == 1:
        return results[0]
    first = results[0]
    if any(result.get("fields") != first.get("fields") for result in results):
        raise ValueError("Paged reads returned incompatible contract fields.")
    values = []
    for result in results:
        page_values = result.get("data", {}).get("values")
        if not isinstance(page_values, list):
            raise ValueError("Paged read returned invalid rows.")
        values.extend(page_values)
    canonical_tab = first["range"].rsplit("!", 1)[0]
    return {**first, "range": f"{canonical_tab}!{first_column}{start}:{last_column}{end}",
            "data": {**first.get("data", {}), "values": values}, "stitched": True}


def _math_finding(scope: Mapping[str, Any], result: Mapping[str, Any], findings: list[dict[str, Any]], math: Any, reader: Callable) -> list[dict[str, Any]]:
    if not isinstance(math, Mapping) or set(math) - {"operation", "n", "group_field", "other_field"} or not isinstance(math.get("operation"), str):
        raise ValueError("Invalid math request.")
    operation = math["operation"]
    allowed = result.get("math_operations", list(APPROVED_OPERATIONS))
    if operation not in APPROVED_OPERATIONS or operation not in allowed:
        raise ValueError("Math operation is not in the data contract.")
    values = [{scope["metric"]: finding["value"]} for finding in findings]
    calculator = getattr(reader, "math", None)
    if not callable(calculator):
        raise ValueError("The configured Data Gateway does not expose MathOps.")
    answer = calculator(
        operation,
        values,
        scope["metric"],
        **{key: value for key, value in math.items() if key != "operation"},
    )
    if not isinstance(answer, (int, float)) or isinstance(answer, bool) or not isfinite(answer):
        raise ValueError("Math operation did not produce a numeric finding.")
    source_range = result["range"]
    pointer = f"sheet://{result['spreadsheet_id']}/{source_range}"
    digest = sha256((pointer + "|" + scope["metric"] + "|" + operation).encode()).hexdigest()
    return [{"id": f"finding-{digest[:16]}", "claim": f"Computed {operation} for {scope['metric']}.",
             "metric": scope["metric"], "segment": scope["segment"],
             "time_range": scope["time_range"] or {"start": None, "end": None}, "value": float(answer),
             "basis": f"{'stitched ' if result.get('stitched') else ''}{source_range}; math {operation}",
             "source_pointer": pointer, "confidence": min(finding["confidence"] for finding in findings),
             "assumptions": ["Approved math operation ran only on rows returned by the Data Gateway."]}]


def _column_number(column: str) -> int:
    number = 0
    for character in column:
        number = number * 26 + ord(character) - ord("A") + 1
    return number


def _clarification_envelope(questions: list[str]) -> dict[str, Any]:
    return {
        "status": "needs_clarification",
        "findings": [],
        "clarifying_questions": questions,
        "narrative": None,
    }


def failed_diagnostic_envelope(message: str) -> dict[str, Any]:
    """Build a schema-valid failure response without leaking implementation details."""
    return {
        "status": "failed",
        "findings": [],
        "clarifying_questions": [],
        "narrative": message,
    }
