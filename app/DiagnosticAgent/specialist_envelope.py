"""Schema-valid Diagnostic analyst envelopes at the specialist A2A seam."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from typing import Any, Mapping, Callable
from math import isfinite
import re


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
        result = reader(read["operation"], read["arguments"])
        findings = _sheet_findings(normalized, result)
    except Exception:
        return failed_diagnostic_envelope("The policy-gated Sheet read could not be completed.")
    if not findings:
        return _clarification_envelope(["The approved range contains no matching numeric observations; clarify the range or metric."])
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
