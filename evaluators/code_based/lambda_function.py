"""Deterministic AgentCore evaluator entrypoint for the frozen eval contracts.

The event must include an evaluator name, trace attributes, and the scenario
assertions.  It deliberately returns a per-scenario result; thresholds belong
to the later baseline-policy step, not this evaluator.
"""

from __future__ import annotations


def handler(event: dict, _context: object) -> dict:
    name = event.get("evaluator_name")
    assertions = event.get("assertions", {})
    trace = event.get("trace", {})
    if not isinstance(name, str) or not isinstance(assertions, dict) or not isinstance(trace, dict):
        return {"result": "ERROR", "reason": "evaluator_name, assertions, and trace are required objects"}

    expected = {
        "DataBoundaryViolation": assertions.get("data_boundary", {}).get("expected_decision"),
        "SecurityGuardrailViolation": assertions.get("security_guardrail", {}).get("expected_action"),
        "BestEffortConfirmationGating": assertions.get("best_effort_confirmation", {}).get("expected_needs_clarification"),
        "CitationLinkIntegrity": True,
        "EnvelopeSchemaConformance": True,
        "DelegationOrderingTrajectory": True,
    }.get(name)
    actual = {
        "DataBoundaryViolation": trace.get("data_boundary_decision"),
        "SecurityGuardrailViolation": trace.get("guardrail_action"),
        "BestEffortConfirmationGating": trace.get("needs_clarification"),
        "CitationLinkIntegrity": trace.get("citation_links_valid"),
        "EnvelopeSchemaConformance": trace.get("envelope_valid"),
        "DelegationOrderingTrajectory": trace.get("trajectory_valid"),
    }.get(name)
    if expected is None or actual is None:
        return {"result": "ERROR", "reason": f"missing assertion or trace attribute for {name}"}
    return {"result": "PASS" if actual == expected else "FAIL", "expected": expected, "actual": actual}
