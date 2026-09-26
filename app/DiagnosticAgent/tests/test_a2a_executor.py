import json
from types import SimpleNamespace
import unittest

from main import LangGraphA2AExecutor, graph


class RecordingQueue:
    def __init__(self) -> None:
        self.events = []

    async def enqueue_event(self, event) -> None:
        self.events.append(event)


class NarrativeGraph:
    async def ainvoke(self, payload):
        return {"messages": [SimpleNamespace(content="Model-authored optional narrative.")]}


class FailingNarrativeGraph:
    async def ainvoke(self, payload):
        raise RuntimeError("Bedrock is unavailable")


class DiagnosticA2AExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_emits_progress_before_a_single_json_envelope_artifact(self) -> None:
        executor = LangGraphA2AExecutor(NarrativeGraph())
        context = SimpleNamespace(
            current_task=SimpleNamespace(id="task-001", context_id="investigation-001"),
            get_user_input=lambda: json.dumps(
                {
                    "task_id": "task-001",
                    "context_id": "investigation-001",
                    "objective": "Investigate the revenue decline.",
                    "scope": {
                        "metric": "revenue",
                        "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                    },
                }
            ),
        )
        event_queue = RecordingQueue()

        await executor.execute(context, event_queue)

        event_types = [type(event).__name__ for event in event_queue.events]
        artifact_index = event_types.index("TaskArtifactUpdateEvent")
        self.assertIn("TaskStatusUpdateEvent", event_types[:artifact_index])
        artifact = event_queue.events[artifact_index].artifact
        self.assertEqual(1, len(artifact.parts))
        envelope = json.loads(artifact.parts[0].text)
        self.assertEqual("complete", envelope["status"])
        self.assertEqual("Model-authored optional narrative.", envelope["narrative"])

    async def test_default_suite_calls_the_real_bedrock_model(self) -> None:
        executor = LangGraphA2AExecutor(graph)
        context = SimpleNamespace(
            current_task=SimpleNamespace(id="task-real-model", context_id="investigation-real-model"),
            get_user_input=lambda: json.dumps(
                {
                    "task_id": "task-real-model",
                    "context_id": "investigation-real-model",
                    "objective": "Investigate the revenue decline.",
                    "scope": {
                        "metric": "revenue",
                        "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                    },
                }
            ),
        )
        event_queue = RecordingQueue()

        await executor.execute(context, event_queue)

        artifact = next(
            event.artifact
            for event in event_queue.events
            if type(event).__name__ == "TaskArtifactUpdateEvent"
        )
        envelope = json.loads(artifact.parts[0].text)
        self.assertEqual("complete", envelope["status"])
        self.assertIsInstance(envelope["narrative"], str)
        self.assertTrue(envelope["narrative"].strip())

    async def test_model_failure_keeps_the_deterministic_envelope_complete(self) -> None:
        executor = LangGraphA2AExecutor(FailingNarrativeGraph())
        context = SimpleNamespace(
            current_task=SimpleNamespace(id="task-failure", context_id="investigation-failure"),
            get_user_input=lambda: json.dumps(
                {
                    "task_id": "task-failure",
                    "context_id": "investigation-failure",
                    "objective": "Investigate the revenue decline.",
                    "scope": {
                        "metric": "revenue",
                        "time_range": {"start": "2026-01-01", "end": "2026-01-31"},
                    },
                }
            ),
        )
        event_queue = RecordingQueue()

        await executor.execute(context, event_queue)

        artifact = next(
            event.artifact
            for event in event_queue.events
            if type(event).__name__ == "TaskArtifactUpdateEvent"
        )
        envelope = json.loads(artifact.parts[0].text)
        self.assertEqual("complete", envelope["status"])
        self.assertTrue(envelope["findings"])
        self.assertIsNone(envelope["narrative"])

    async def test_non_text_payload_returns_a_failed_envelope(self) -> None:
        executor = LangGraphA2AExecutor(NarrativeGraph())
        context = SimpleNamespace(
            current_task=SimpleNamespace(id="task-non-text", context_id="investigation-non-text"),
            get_user_input=lambda: None,
        )
        event_queue = RecordingQueue()

        await executor.execute(context, event_queue)

        artifact = next(
            event.artifact
            for event in event_queue.events
            if type(event).__name__ == "TaskArtifactUpdateEvent"
        )
        envelope = json.loads(artifact.parts[0].text)
        self.assertEqual("failed", envelope["status"])


if __name__ == "__main__":
    unittest.main()
