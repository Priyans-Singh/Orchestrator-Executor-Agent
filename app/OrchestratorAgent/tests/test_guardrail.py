import json
import unittest
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from guardrail import GuardedAuthor, GuardrailAssessment, GuardrailPolicy, emit_guardrail_span
from investigation import Investigation
from test_investigation import AuthorAdapter, SpecialistAdapter, FINDINGS


class BedrockClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def apply_guardrail(self, **request):
        self.requests.append(request)
        return self.response


class GuardrailCheckTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("guardrail-test")
        self.patcher = patch("guardrail.trace.get_tracer", return_value=self.tracer)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.provider.shutdown)

    async def test_check_exports_only_triggered_content_categories(self):
        client = BedrockClient({"action": "GUARDRAIL_INTERVENED", "assessments": [{
            "contentPolicy": {"filters": [
                {"type": "PROMPT_ATTACK", "confidence": "HIGH", "action": "BLOCKED"},
                {"type": "VIOLENCE", "confidence": "LOW", "action": "NONE"},
            ]},
        }], "outputs": [{"text": "PRIVATE FLAGGED TEXT"}]})
        assessment = await GuardrailPolicy("shared-policy", "1", client).check(
            "PRIVATE FLAGGED TEXT", "INPUT")
        spans = self.exporter.get_finished_spans()
        self.assertEqual(1, len(spans))
        self.assertEqual("guardrail.check", spans[0].name)
        self.assertEqual("GUARDRAIL_INTERVENED", spans[0].attributes["guardrail.action"])
        expected = [{"policy_type": "contentPolicy", "category": "PROMPT_ATTACK", "confidence": "HIGH"}]
        self.assertEqual(expected, assessment.triggered_policies)
        self.assertEqual(expected, json.loads(spans[0].attributes["guardrail.triggered_policies"]))
        self.assertNotIn("PRIVATE FLAGGED TEXT", str(spans[0].attributes))
        self.assertEqual("shared-policy", client.requests[0]["guardrailIdentifier"])
        self.assertEqual("1", client.requests[0]["guardrailVersion"])

    async def test_policies_without_confidence_use_safe_categories_without_matches(self):
        client = BedrockClient({"action": "GUARDRAIL_INTERVENED", "assessments": [{
            "topicPolicy": {"topics": [{"name": "PRIVATE TOPIC", "type": "DENY", "action": "BLOCKED"}]},
            "wordPolicy": {
                "customWords": [{"match": "PRIVATE WORD", "action": "BLOCKED"}],
                "managedWordLists": [{"match": "PRIVATE WORD", "type": "PROFANITY", "action": "BLOCKED"}],
            },
            "sensitiveInformationPolicy": {
                "piiEntities": [{"match": "private@example.com", "type": "EMAIL", "action": "ANONYMIZED"}],
                "regexes": [{"name": "PRIVATE REGEX", "match": "PRIVATE MATCH", "regex": "PRIVATE PATTERN",
                             "action": "BLOCKED"}],
            },
            "contextualGroundingPolicy": {"filters": [
                {"type": "GROUNDING", "score": 0.1, "threshold": 0.8, "action": "BLOCKED"},
                {"type": "RELEVANCE", "score": 0.9, "threshold": 0.8, "action": "NONE"},
            ]},
        }]})
        await GuardrailPolicy("shared-policy", "1", client).check("PRIVATE INPUT", "INPUT")
        span = self.exporter.get_finished_spans()[0]
        self.assertEqual([
            {"policy_type": "topicPolicy", "category": "DENY"},
            {"policy_type": "wordPolicy", "category": "CUSTOM_WORD"},
            {"policy_type": "wordPolicy", "category": "PROFANITY"},
            {"policy_type": "sensitiveInformationPolicy", "category": "EMAIL"},
            {"policy_type": "sensitiveInformationPolicy", "category": "REGEX"},
            {"policy_type": "contextualGroundingPolicy", "category": "GROUNDING"},
        ], json.loads(span.attributes["guardrail.triggered_policies"]))
        self.assertNotIn("PRIVATE", str(span.attributes))
        self.assertNotIn("private@example.com", str(span.attributes))

    async def test_check_span_covers_bedrock_call_and_shares_parent_trace(self):
        class InspectingClient(BedrockClient):
            def apply_guardrail(inner, **request):
                inner.check_context = trace.get_current_span().get_span_context()
                return super().apply_guardrail(**request)

        client = InspectingClient({"action": "NONE", "assessments": []})
        with self.tracer.start_as_current_span("investigation") as parent:
            await GuardrailPolicy("shared-policy", "1", client).check("Revenue is 12345", "OUTPUT")
        check = self.exporter.get_finished_spans()[0]
        self.assertEqual(check.context.span_id, client.check_context.span_id)
        self.assertEqual(parent.get_span_context().span_id, check.parent.span_id)
        self.assertEqual(parent.get_span_context().trace_id, check.context.trace_id)
        self.assertEqual("NONE", check.attributes["guardrail.action"])
        self.assertEqual("OUTPUT", check.attributes["guardrail.source"])
        self.assertEqual([], json.loads(check.attributes["guardrail.triggered_policies"]))

    async def test_failed_check_exports_error_without_provider_exception_text(self):
        class FailingClient:
            def apply_guardrail(inner, **request):
                raise RuntimeError("PRIVATE FLAGGED TEXT in provider error")

        with self.assertRaises(RuntimeError):
            await GuardrailPolicy("shared-policy", "1", FailingClient()).check("PRIVATE FLAGGED TEXT", "INPUT")
        spans = self.exporter.get_finished_spans()
        self.assertEqual(1, len(spans))
        self.assertEqual(StatusCode.ERROR, spans[0].status.status_code)
        self.assertEqual("ERROR", spans[0].attributes["guardrail.action"])
        self.assertNotIn("PRIVATE", str(spans[0].attributes) + str(spans[0].events) + str(spans[0].status.description))

    async def test_specialist_reuses_shared_policy_with_its_own_span_identity(self):
        environ = {"GUARDRAIL_ID": "shared-policy", "GUARDRAIL_VERSION": "1"}
        policy = GuardrailPolicy.from_environment(environ, agent_name="DiagnosticAgent")
        policy.client = BedrockClient({"action": "NONE", "assessments": []})
        await policy.check("Revenue is 12345", "INPUT")
        span = self.exporter.get_finished_spans()[0]
        self.assertEqual("shared-policy", span.attributes["guardrail.id"])
        self.assertEqual("DiagnosticAgent", span.attributes["agent.name"])

    async def test_detected_filter_is_reported_when_policy_is_in_observe_mode(self):
        client = BedrockClient({"action": "NONE", "assessments": [{"contentPolicy": {"filters": [
            {"type": "PROMPT_ATTACK", "confidence": "HIGH", "action": "NONE", "detected": True},
            {"type": "VIOLENCE", "confidence": "NONE", "action": "NONE", "detected": False},
        ]}}]})
        await GuardrailPolicy("shared-policy", "1", client).check("PRIVATE INPUT", "INPUT")
        span = self.exporter.get_finished_spans()[0]
        self.assertEqual("NONE", span.attributes["guardrail.action"])
        self.assertEqual([{"policy_type": "contentPolicy", "category": "PROMPT_ATTACK", "confidence": "HIGH"}],
                         json.loads(span.attributes["guardrail.triggered_policies"]))

    async def test_orchestrator_checks_input_and_output_with_one_shared_policy(self):
        policy = GuardrailPolicy.from_environment({"GUARDRAIL_ID": "shared-policy", "GUARDRAIL_VERSION": "1"})
        client = BedrockClient({"action": "NONE", "assessments": []})
        policy.client = client
        investigation = Investigation(GuardedAuthor(AuthorAdapter(), policy), {
            "diagnostic": SpecialistAdapter({"status": "complete", "findings": FINDINGS})})
        events = [event async for event in investigation.stream("Why did revenue fall?", "task-1", "context-1")]
        self.assertEqual("complete", events[-1]["result"]["investigation_status"])
        self.assertEqual(FINDINGS, events[-1]["result"]["findings"])
        spans = self.exporter.get_finished_spans()
        self.assertEqual(["INPUT", "OUTPUT"], [span.attributes["guardrail.source"] for span in spans])
        self.assertEqual(["shared-policy", "shared-policy"], [span.attributes["guardrail.id"] for span in spans])
        self.assertEqual(["OrchestratorAgent", "OrchestratorAgent"], [span.attributes["agent.name"] for span in spans])
        self.assertEqual("Why did revenue fall?", client.requests[0]["content"][0]["text"]["text"])

    async def test_blocked_input_fails_investigation_before_delegation(self):
        policy = GuardrailPolicy("shared-policy", "1", BedrockClient({
            "action": "GUARDRAIL_INTERVENED", "assessments": []}))
        specialist = SpecialistAdapter({"status": "complete", "findings": FINDINGS})
        investigation = Investigation(GuardedAuthor(AuthorAdapter(), policy), {"diagnostic": specialist})
        events = [event async for event in investigation.stream("PRIVATE FLAGGED TEXT", "task-1", "context-1")]
        self.assertEqual("failed", events[-1]["result"]["investigation_status"])
        self.assertEqual([], specialist.requests)
        spans = self.exporter.get_finished_spans()
        self.assertEqual(1, len(spans))
        self.assertEqual("GUARDRAIL_INTERVENED", spans[0].attributes["guardrail.action"])
        self.assertNotIn("PRIVATE FLAGGED TEXT", str(spans[0].attributes))

    async def test_blocked_output_fails_investigation_without_releasing_synthesis(self):
        class OutputBlockingClient(BedrockClient):
            def apply_guardrail(inner, **request):
                return {"action": "GUARDRAIL_INTERVENED" if request["source"] == "OUTPUT" else "NONE",
                        "assessments": []}

        policy = GuardrailPolicy("shared-policy", "1", OutputBlockingClient({}))
        investigation = Investigation(GuardedAuthor(AuthorAdapter(), policy), {
            "diagnostic": SpecialistAdapter({"status": "complete", "findings": FINDINGS})})
        events = [event async for event in investigation.stream("Why did revenue fall?", "task-1", "context-1")]
        self.assertEqual("failed", events[-1]["result"]["investigation_status"])
        self.assertNotIn("Revenue and conversion declined", events[-1]["result"]["narrative"])
        spans = self.exporter.get_finished_spans()
        self.assertEqual(["NONE", "GUARDRAIL_INTERVENED"], [span.attributes["guardrail.action"] for span in spans])


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
