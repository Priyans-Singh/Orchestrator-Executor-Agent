"""Exercise the user-facing Investigation through the real A2A executor."""
import json
from types import SimpleNamespace
import unittest

from a2a.helpers import new_text_message
from a2a.types import Role, Task, TaskState, TaskStatus
from main import LangGraphA2AExecutor
from investigation import Investigation
from test_investigation import AuthorAdapter, SpecialistAdapter, FINDINGS


class RecordingQueue:
    def __init__(self):
        self.events = []

    async def enqueue_event(self, event):
        self.events.append(event)


class A2AInvestigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_call_streams_working_then_synthesis_and_completion(self):
        executor = LangGraphA2AExecutor(Investigation(AuthorAdapter(), {
            "diagnostic": SpecialistAdapter({"status": "complete", "findings": FINDINGS})}))
        message = new_text_message("Why did revenue fall?", role=Role.ROLE_USER)
        context = SimpleNamespace(current_task=None, message=message,
                                  get_user_input=lambda: "Why did revenue fall?")
        queue = RecordingQueue()
        await executor.execute(context, queue)
        self.assertIsInstance(queue.events[0], Task)
        artifact_index = next(i for i, e in enumerate(queue.events) if hasattr(e, "artifact"))
        self.assertTrue(any(getattr(getattr(e, "status", None), "state", None) == TaskState.TASK_STATE_WORKING
                            for e in queue.events[1:artifact_index]))
        result = json.loads(queue.events[artifact_index].artifact.parts[0].text)
        self.assertEqual(FINDINGS, result["findings"])
        self.assertEqual(0.4, result["overall_confidence"])
        self.assertEqual(TaskState.TASK_STATE_COMPLETED, queue.events[-1].status.state)

    async def test_clarification_can_resume_in_a_new_executor_with_same_a2a_task(self):
        class Author(AuthorAdapter):
            def __init__(self):
                self.previous = None

            async def plan(self, question, previous):
                self.previous = previous
                if previous and question == "yes":
                    if previous["previous_clarification"]["questions"] != [
                        "Which reporting period should I use?"
                    ]:
                        raise ValueError("Clarification context was not restored")
                    return {"objective": question, "scope": {"metric": "revenue", "time_range": {
                        "start": "2026-01-01", "end": "2026-01-31"}}, "specialists": ["diagnostic"]}
                return {"objective": question, "scope": {"metric": "revenue"},
                        "specialists": ["diagnostic"]}

            async def synthesize(self, evidence):
                return {"narrative": "I need the reporting period.", "recommended_actions": [],
                        "clarifying_questions": ["Which reporting period should I use?"]}

        specialist = SpecialistAdapter({"status": "needs_clarification", "findings": [],
                                        "clarifying_questions": ["RAW SPECIALIST QUESTION"]})
        task = Task(id="task-1", context_id="context-1", status=TaskStatus(state=TaskState.TASK_STATE_WORKING))
        queue = RecordingQueue()
        context = SimpleNamespace(current_task=task, get_user_input=lambda: "Investigate revenue")
        first_author = Author()
        await LangGraphA2AExecutor(Investigation(first_author, {"diagnostic": specialist})).execute(context, queue)
        self.assertEqual(TaskState.TASK_STATE_INPUT_REQUIRED, queue.events[-1].status.state)
        self.assertNotIn("RAW SPECIALIST QUESTION", str(queue.events[-1]))
        task.artifacts.extend(e.artifact for e in queue.events if hasattr(e, "artifact"))
        task.status.CopyFrom(queue.events[-1].status)
        specialist.envelope = {"status": "complete", "findings": FINDINGS}
        context.get_user_input = lambda: "yes"
        resumed_author = Author()
        await LangGraphA2AExecutor(Investigation(resumed_author, {"diagnostic": specialist})).execute(context, RecordingQueue())
        self.assertEqual("task-1", specialist.requests[-1]["task_id"])
        self.assertEqual("context-1", specialist.requests[-1]["context_id"])
        self.assertEqual("Investigate revenue", specialist.requests[-1]["objective"])
        self.assertEqual("yes", specialist.requests[-1]["prior_context"]["answer"])
        self.assertEqual(
            {"narrative": "I need the reporting period.",
             "questions": ["Which reporting period should I use?"]},
            resumed_author.previous["previous_clarification"],
        )

    async def test_default_langgraph_wiring_uses_the_live_diagnostic_a2a_adapter(self):
        from unittest.mock import patch
        from author import build_investigation
        from diagnostic_a2a import DiagnosticA2AAdapter

        with patch("author.DiagnosticA2AAdapter", wraps=DiagnosticA2AAdapter) as diagnostic:
            investigation = build_investigation()
        diagnostic.assert_called_once_with()
        self.assertIsInstance(investigation.specialists["diagnostic"], DiagnosticA2AAdapter)
        from evidence_a2a import EvidenceA2AAdapter
        self.assertIsInstance(investigation.specialists["evidence"], EvidenceA2AAdapter)
