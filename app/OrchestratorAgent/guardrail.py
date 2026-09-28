"""Shared Bedrock Guardrail boundary and safe custom observability span."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from opentelemetry import trace


@dataclass(frozen=True)
class GuardrailAssessment:
    guardrail_id: str
    version: str
    source: str
    action: str
    triggered_policies: list[dict[str, str]]


class Guardrail(Protocol):
    async def check(self, content: str, source: str) -> GuardrailAssessment: ...


def _safe_policies(response: dict[str, Any]) -> list[dict[str, str]]:
    policies: list[dict[str, str]] = []

    def visit(value: Any, policy_type: str | None = None) -> None:
        if isinstance(value, dict):
            current_type = value.get("policyType") or policy_type
            category = value.get("category") or value.get("type") or value.get("name")
            confidence = value.get("confidence")
            if current_type and category and confidence:
                policies.append({"policy_type": str(current_type), "category": str(category),
                                 "confidence": str(confidence)})
            for key, child in value.items():
                visit(child, key if key.endswith("Policy") else current_type)
        elif isinstance(value, list):
            for child in value:
                visit(child, policy_type)

    visit(response.get("assessments", []))
    return policies


def emit_guardrail_span(assessment: GuardrailAssessment, tracer=None) -> None:
    """Emit policy metadata only; raw guarded content must never enter the span."""
    tracer = tracer or trace.get_tracer(__name__)
    safe_policies = [
        {key: policy[key] for key in ("policy_type", "category", "confidence") if key in policy}
        for policy in assessment.triggered_policies
    ]
    with tracer.start_as_current_span("guardrail.check") as span:
        span.set_attribute("guardrail.id", assessment.guardrail_id)
        span.set_attribute("guardrail.version", assessment.version)
        span.set_attribute("guardrail.source", assessment.source)
        span.set_attribute("guardrail.action", assessment.action)
        span.set_attribute("guardrail.triggered_policies", json.dumps(safe_policies, separators=(",", ":")))
        span.set_attribute("agent.name", "OrchestratorAgent")


class GuardrailPolicy:
    def __init__(self, guardrail_id: str, version: str, client=None):
        self.guardrail_id = guardrail_id
        self.version = version
        self.client = client

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "GuardrailPolicy | None":
        environ = os.environ if environ is None else environ
        guardrail_id = environ.get("GUARDRAIL_ID")
        return cls(guardrail_id, environ.get("GUARDRAIL_VERSION", "DRAFT")) if guardrail_id else None

    async def check(self, content: str, source: str) -> GuardrailAssessment:
        if not isinstance(content, str):
            raise ValueError("Guardrail content must be text")
        if self.client is None:
            import boto3  # type: ignore[import-untyped]
            self.client = boto3.client("bedrock-runtime")
        response = self.client.apply_guardrail(
            guardrailIdentifier=self.guardrail_id,
            guardrailVersion=self.version,
            source=source,
            content=[{"text": {"text": content}}],
        )
        assessment = GuardrailAssessment(
            guardrail_id=self.guardrail_id, version=self.version, source=source,
            action=str(response.get("action", "NONE")), triggered_policies=_safe_policies(response),
        )
        emit_guardrail_span(assessment)
        return assessment


class GuardedAuthor:
    """Keep LangGraph unchanged while applying the one shared policy at its edge."""

    def __init__(self, author, guardrail: Guardrail | None):
        self.author = author
        self.guardrail = guardrail

    async def plan(self, question: str, previous: dict[str, Any] | None,
                   recalled: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if self.guardrail:
            checked = await self.guardrail.check(question, "INPUT")
            if checked.action == "GUARDRAIL_INTERVENED":
                raise ValueError("Input was blocked by the shared guardrail")
        try:
            return await self.author.plan(question, previous, recalled)
        except TypeError:
            return await self.author.plan(question, previous)

    async def synthesize(self, evidence: dict[str, Any]) -> dict[str, Any]:
        authored = await self.author.synthesize(evidence)
        if self.guardrail:
            checked = await self.guardrail.check(json.dumps(authored, allow_nan=False), "OUTPUT")
            if checked.action == "GUARDRAIL_INTERVENED":
                raise ValueError("Output was blocked by the shared guardrail")
        return authored
