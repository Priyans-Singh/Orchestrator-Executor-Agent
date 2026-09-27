"""User-facing A2A transport for the Investigation seam."""
import json

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part, TaskState

from investigation import Investigation


class LangGraphA2AExecutor(AgentExecutor):
    def __init__(self, investigation: Investigation):
        self.investigation = investigation

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task is None and context.message is None:
            raise ValueError("An A2A user message is required")
        task = context.current_task
        if task is None:
            assert context.message is not None
            task = new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        previous = None
        if task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
            for artifact in reversed(task.artifacts):
                if artifact.name == "investigation-synthesis":
                    saved = (artifact.metadata["investigation_state"]
                             if "investigation_state" in artifact.metadata else None)
                    if isinstance(saved, str):
                        previous = json.loads(saved)
                    break
        async for event in self.investigation.stream(
            context.get_user_input(), task.id, task.context_id, previous
        ):
            if event["type"] == "progress":
                await updater.start_work(updater.new_agent_message([Part(text=event["message"])]))
                continue
            result = event["result"]
            await updater.add_artifact(
                [Part(text=json.dumps(result, allow_nan=False))], name="investigation-synthesis",
                metadata={"investigation_state": json.dumps(event["state"])},
            )
            if result["investigation_status"] == "needs_clarification":
                text = result["narrative"] + "\n" + "\n".join(result["clarifying_questions"])
                await updater.requires_input(updater.new_agent_message([Part(text=text)]))
            elif result["investigation_status"] == "failed":
                await updater.failed()
            else:
                await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task:
            task = context.current_task
            await TaskUpdater(event_queue, task.id, task.context_id).cancel()


card = AgentCard(
    name="OrchestratorAgent",
    description="Plans and synthesizes RCA investigations through specialist adapters",
    version="0.1.0",
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="investigate",
            name="Investigate",
            description="Investigate business symptoms with evidence-backed findings",
            tags=["rca"],
        )
    ],
    default_input_modes=["text"],
    default_output_modes=["text"],
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            protocol_version="1.0",
            url="http://localhost:9000/",
        )
    ],
)

if __name__ == "__main__":
    from bedrock_agentcore.runtime import serve_a2a
    from author import build_investigation

    serve_a2a(LangGraphA2AExecutor(build_investigation()), card)
