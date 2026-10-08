"""Evidence transport exercised through the Investigation boundary."""
import json
import unittest

from a2a.helpers import new_text_message
from a2a.types import Artifact, StreamResponse, TaskArtifactUpdateEvent
from opentelemetry import baggage

from evidence_a2a import EvidenceA2AAdapter
from investigation import Investigation
from test_investigation import AuthorAdapter, SpecialistAdapter, FINDINGS, CITATION


class EvidenceInvestigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_evidence_receives_findings_and_returns_unchanged_citations(self):
        requests = []

        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {"topic": "demand"},
                        "specialists": ["evidence", "diagnostic"]}

        class Client:
            async def send_message(self, request):
                requests.append(json.loads(request.message.parts[0].text))
                yield StreamResponse(artifact_update=TaskArtifactUpdateEvent(artifact=Artifact(
                    name="evidence-envelope", parts=[new_text_message(json.dumps({
                        "status": "complete", "citations": [CITATION]})).parts[0]])))

            async def close(self):
                pass

        async def connect(url, token):
            self.assertEqual("https://evidence.example", url)
            self.assertEqual("jwt", token)
            return Client()

        events = [event async for event in Investigation(Author(), {
            "diagnostic": SpecialistAdapter({"status": "complete", "findings": FINDINGS}),
            "evidence": EvidenceA2AAdapter("https://evidence.example", "jwt", connect),
        }).stream("Why did revenue fall?", "task", "context")]
        self.assertEqual(FINDINGS, requests[0]["scope"]["findings"])
        self.assertEqual([CITATION], events[-1]["result"]["citations"])
        self.assertEqual("complete", events[-1]["result"]["investigation_status"])

    async def test_standalone_web_response_is_background_without_confidence_or_actions(self):
        snippet = {key: value for key, value in CITATION.items()
                   if key not in {"corroborates_finding_id", "challenges_finding_id"}}
        requests = []

        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {"topic": "demand"},
                        "specialists": ["evidence"]}

        class Client:
            closed = False

            async def send_message(self, request):
                requests.append(request.message)
                self.context_id = baggage.get_baggage("context_id")
                yield StreamResponse(artifact_update=TaskArtifactUpdateEvent(artifact=Artifact(
                    name="evidence-envelope", parts=[new_text_message(json.dumps({
                        "status": "complete", "context_snippets": [snippet]})).parts[0]])))

            async def close(self):
                self.closed = True

        client = Client()

        async def connect(url, token):
            return client

        events = [event async for event in Investigation(Author(), {
            "evidence": EvidenceA2AAdapter("https://evidence.example", "jwt", connect),
        }).stream("What is happening to demand?", "task", "context")]
        result = events[-1]["result"]
        self.assertEqual([snippet], result["context_snippets"])
        self.assertEqual([], result["citations"])
        self.assertIsNone(result["overall_confidence"])
        self.assertEqual([], result["recommended_actions"])
        self.assertEqual("task", requests[0].task_id)
        self.assertEqual("context", requests[0].context_id)
        self.assertEqual([], json.loads(requests[0].parts[0].text)["scope"]["findings"])
        self.assertEqual("context", client.context_id)
        self.assertTrue(client.closed)

    async def test_missing_evidence_configuration_fails_without_synthetic_results(self):
        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {}, "specialists": ["evidence"]}

        events = [event async for event in Investigation(Author(), {
            "evidence": EvidenceA2AAdapter("", ""),
        }).stream("What happened to demand?", "task", "context")]
        self.assertEqual("failed", events[-1]["result"]["investigation_status"])
        self.assertEqual([], events[-1]["result"]["context_snippets"])
