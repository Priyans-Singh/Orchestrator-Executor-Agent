"""Live Diagnostic A2A adapter at the Investigation specialist seam."""
import json
from pathlib import Path
import unittest

from a2a.helpers import new_text_message
from a2a.types import Artifact, Role, StreamResponse, TaskArtifactUpdateEvent, TaskStatus, TaskStatusUpdateEvent
from opentelemetry import baggage

from diagnostic_a2a import DiagnosticA2AAdapter


REQUEST = {
    "task_id": "investigation-task",
    "context_id": "investigation-context",
    "objective": "Find the revenue driver.",
    "scope": {"metric": "revenue"},
    "prior_context": {},
}
ENVELOPE = {
    "status": "complete",
    "findings": [{
        "id": "revenue-driver", "claim": "Revenue declined", "metric": "revenue",
        "segment": None, "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
        "value": -12.0, "basis": "Performance!A1:D10", "confidence": 0.8,
        "assumptions": [],
    }],
    "clarifying_questions": [],
}


class RecordingClient:
    def __init__(self):
        self.request = None
        self.baggage_context_id = None
        self.closed = False

    async def send_message(self, request):
        self.request = request
        self.baggage_context_id = baggage.get_baggage("context_id")
        yield StreamResponse(status_update=TaskStatusUpdateEvent(status=TaskStatus(
            message=new_text_message("Reading the approved Sheet range.", role=Role.ROLE_AGENT))))
        yield StreamResponse(artifact_update=TaskArtifactUpdateEvent(artifact=Artifact(
            name="diagnostic-envelope", parts=[new_text_message(json.dumps(ENVELOPE)).parts[0]])))

    async def close(self):
        self.closed = True


class DiagnosticA2ATests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_the_investigation_delegation_to_diagnostic_and_relays_its_envelope(self):
        client = RecordingClient()

        async def connect(url, bearer_token):
            self.assertEqual("https://diagnostic.example", url)
            self.assertEqual("jwt", bearer_token)
            return client

        events = [event async for event in DiagnosticA2AAdapter(
            url="https://diagnostic.example", bearer_token="jwt", connect=connect).stream(REQUEST)]

        self.assertEqual("Reading the approved Sheet range.", events[0])
        self.assertEqual(ENVELOPE, events[1])
        self.assertTrue(client.closed)
        self.assertEqual("investigation-context", client.baggage_context_id)
        message = client.request.message
        self.assertEqual("investigation-task", message.task_id)
        self.assertEqual("investigation-context", message.context_id)
        payload = json.loads(message.parts[0].text)
        self.assertEqual(REQUEST, payload)
        self.assertNotIn("traceParent", payload)
        self.assertNotIn("traceId", payload)


class RuntimeAuthorizationTests(unittest.TestCase):
    def test_diagnostic_uses_the_orchestrator_custom_jwt_authorizer(self):
        project = json.loads((Path(__file__).parents[3] / "agentcore" / "agentcore.json").read_text())
        runtimes = {runtime["name"]: runtime for runtime in project["runtimes"]}
        self.assertEqual("CUSTOM_JWT", runtimes["DiagnosticAgent"]["authorizerType"])
        self.assertEqual(
            runtimes["OrchestratorAgent"]["authorizerConfiguration"],
            runtimes["DiagnosticAgent"]["authorizerConfiguration"],
        )


if __name__ == "__main__":
    unittest.main()
