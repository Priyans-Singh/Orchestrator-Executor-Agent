import json
import unittest

from guardrail import GuardrailAssessment, GuardrailPolicy, emit_guardrail_span


class Span:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


class SpanContext:
    def __init__(self, span):
        self.span = span

    def __enter__(self):
        return self.span

    def __exit__(self, *_):
        return False


class Tracer:
    def __init__(self):
        self.name = None
        self.span = Span()

    def start_as_current_span(self, name):
        self.name = name
        return SpanContext(self.span)


class GuardrailSpanTests(unittest.TestCase):
    def test_span_records_safe_policy_details_without_flagged_text(self):
        tracer = Tracer()
        emit_guardrail_span(GuardrailAssessment(
            guardrail_id="shared-policy", version="1", source="INPUT",
            action="GUARDRAIL_INTERVENED", triggered_policies=[{
                "policy_type": "contentPolicy", "category": "VIOLENCE", "confidence": "HIGH",
                "raw_text": "do not retain this",
            }],
        ), tracer=tracer)
        self.assertEqual("guardrail.check", tracer.name)
        self.assertEqual("GUARDRAIL_INTERVENED", tracer.span.attributes["guardrail.action"])
        policies = json.loads(tracer.span.attributes["guardrail.triggered_policies"])
        self.assertEqual([{"policy_type": "contentPolicy", "category": "VIOLENCE", "confidence": "HIGH"}],
                         policies)
        self.assertNotIn("do not retain this", str(tracer.span.attributes))

    def test_policy_reads_one_shared_id_and_version_from_environment(self):
        policy = GuardrailPolicy.from_environment({"GUARDRAIL_ID": "shared-policy", "GUARDRAIL_VERSION": "DRAFT"})
        self.assertEqual("shared-policy", policy.guardrail_id)
        self.assertEqual("DRAFT", policy.version)
