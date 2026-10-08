"""Shared Bedrock Guardrail boundary and safe custom observability span."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode


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

    # Inspect only documented assessment collections, never matches, names, or text.
    collections = {
        "topicPolicy": (("topics", "DENY"),),
        "contentPolicy": (("filters", None),),
        "wordPolicy": (("customWords", "CUSTOM_WORD"), ("managedWordLists", None)),
        "sensitiveInformationPolicy": (("piiEntities", None), ("regexes", "REGEX")),
        "contextualGroundingPolicy": (("filters", None),),
    }
    for assessment in response.get("assessments", []):
        for policy_type, groups in collections.items():
            for group, fallback in groups:
                for entry in assessment.get(policy_type, {}).get(group, []):
                    if (entry.get("action") not in {"BLOCKED", "ANONYMIZED"}
                            and entry.get("detected") is not True):
                        continue
                    category = fallback or entry.get("type")
                    if not category:
                        continue
                    policy = {"policy_type": policy_type, "category": str(category)}
                    if entry.get("confidence") is not None:
                        policy["confidence"] = str(entry["confidence"])
                    policies.append(policy)
    return policies


def _record_assessment(span: Span, assessment: GuardrailAssessment, agent_name: str) -> None:
    safe_policies = [
        {key: policy[key] for key in ("policy_type", "category", "confidence") if key in policy}
        for policy in assessment.triggered_policies
    ]
    span.set_attribute("guardrail.id", assessment.guardrail_id)
    span.set_attribute("guardrail.version", assessment.version)
    span.set_attribute("guardrail.source", assessment.source)
    span.set_attribute("guardrail.action", assessment.action)
    span.set_attribute("guardrail.triggered_policies", json.dumps(safe_policies, separators=(",", ":")))
    span.set_attribute("agent.name", agent_name)


def emit_guardrail_span(assessment: GuardrailAssessment, tracer=None,
                        agent_name: str = "OrchestratorAgent") -> None:
    """Emit policy metadata only; raw guarded content must never enter the span."""
    tracer = tracer or trace.get_tracer(__name__)
    with tracer.start_as_current_span("guardrail.check") as span:
        _record_assessment(span, assessment, agent_name)


class GuardrailPolicy:
    def __init__(self, guardrail_id: str, version: str, client=None,
                 agent_name: str = "OrchestratorAgent"):
        self.guardrail_id = guardrail_id
        self.version = version
        self.client = client
        self.agent_name = agent_name

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None,
                         agent_name: str = "OrchestratorAgent") -> "GuardrailPolicy | None":
        environ = os.environ if environ is None else environ
        guardrail_id = environ.get("GUARDRAIL_ID")
        return cls(guardrail_id, environ.get("GUARDRAIL_VERSION", "DRAFT"),
                   agent_name=agent_name) if guardrail_id else None

    async def check(self, content: str, source: str) -> GuardrailAssessment:
        if not isinstance(content, str):
            raise ValueError("Guardrail content must be text")
        tracer = trace.get_tracer(__name__)
        # Provider errors can echo the input. Do not record their text on this span.
        with tracer.start_as_current_span(
            "guardrail.check", record_exception=False, set_status_on_exception=False,
        ) as span:
            _record_assessment(span, GuardrailAssessment(
                self.guardrail_id, self.version, source, "ERROR", [],
            ), self.agent_name)
            try:
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
                    action=str(response["action"]), triggered_policies=_safe_policies(response),
                )
                _record_assessment(span, assessment, self.agent_name)
                return assessment
            except Exception:
                span.set_status(StatusCode.ERROR)
                raise


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
