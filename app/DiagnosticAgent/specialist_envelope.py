"""Schema-valid Diagnostic analyst envelopes at the specialist A2A seam."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from typing import Any, Mapping


def build_diagnostic_envelope(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic Diagnostic envelope for one delegation request.

    The fake adapter is deliberately the source of every load-bearing field.
    A caller may later add a narrative, but no response consumer must parse it.
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

    status = "complete" if time_range is not None else "partial"
    return {
        "status": status,
        "findings": [_fake_finding(normalized, is_partial=status == "partial")],
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


def _fake_finding(normalized: Mapping[str, Any], *, is_partial: bool) -> dict[str, Any]:
    time_range = normalized["time_range"]
    canonical_time_range = time_range or {"start": None, "end": None}
    identity = "|".join(
        [
            normalized["metric"],
            normalized["segment"] or "",
            canonical_time_range["start"] or "",
            canonical_time_range["end"] or "",
        ]
    )
    digest = sha256(identity.encode("utf-8")).hexdigest()
    value = round((int(digest[:8], 16) % 100_000) / 100, 2)
    confidence = round(0.55 + ((int(digest[8:12], 16) % 36) / 100), 2)
    assumptions = ["Value and confidence come from the deterministic fake Sheet adapter."]
    if is_partial:
        assumptions.append("time_range was not supplied; this is confirmed best-effort analysis.")

    return {
        "id": f"finding-{digest[:16]}",
        "claim": f"Synthetic diagnostic signal for {normalized['metric']}.",
        "metric": normalized["metric"],
        "segment": normalized["segment"],
        "time_range": canonical_time_range,
        "value": float(value),
        "basis": "Deterministic fake Sheet adapter; no Google Sheets data was read.",
        "source_pointer": f"fake-sheet://{normalized['metric']}/{normalized['segment'] or 'all'}",
        "confidence": confidence,
        "assumptions": assumptions,
    }


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
