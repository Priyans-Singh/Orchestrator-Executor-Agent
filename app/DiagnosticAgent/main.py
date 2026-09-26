import json

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part
from bedrock_agentcore.runtime import serve_a2a
from model.load import load_model
from specialist_envelope import build_diagnostic_envelope, failed_diagnostic_envelope

LangchainInstrumentor().instrument()


@tool
def add_numbers(a: int, b: int) -> int:
    """Return the sum of two numbers."""
    return a + b


tools = [add_numbers]


SYSTEM_PROMPT = """You write a concise, non-load-bearing narrative for a diagnostic
envelope. Do not introduce facts, findings, values, or recommendations beyond the
structured result supplied in the user message."""

model = load_model()
graph = create_react_agent(model, tools=tools, prompt=SYSTEM_PROMPT)


class LangGraphA2AExecutor(AgentExecutor):
    """Wraps a LangGraph CompiledGraph as an a2a-sdk AgentExecutor."""

    def __init__(self, graph):
        self.graph = graph

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.start_work(
            updater.new_agent_message([Part(text="Validating the diagnostic delegation request.")])
        )
        envelope = self._build_envelope(context.get_user_input(), task.id, task.context_id)
        if envelope["status"] in {"complete", "partial"}:
            await updater.start_work(
                updater.new_agent_message([Part(text="Producing the optional diagnostic narrative.")])
            )
            try:
                envelope["narrative"] = await self._generate_narrative(envelope)
            except Exception:
                envelope["narrative"] = None

        await updater.add_artifact([Part(text=json.dumps(envelope))], name="diagnostic-envelope")
        if envelope["status"] == "needs_clarification":
            await updater.requires_input()
        elif envelope["status"] == "failed":
            await updater.failed()
        else:
            await updater.complete()

    @staticmethod
    def _build_envelope(user_text: str, task_id: str, context_id: str) -> dict:
        if not isinstance(user_text, str):
            return failed_diagnostic_envelope("Delegation request text must be a string.")
        try:
            request = json.loads(user_text)
        except json.JSONDecodeError:
            request = {}
        if not isinstance(request, dict):
            request = {}
        if request.get("task_id") != task_id or request.get("context_id") != context_id:
            request = {}
        if not request:
            request = {"task_id": task_id, "context_id": context_id}
        return build_diagnostic_envelope(request)

    async def _generate_narrative(self, envelope: dict) -> str:
        result = await self.graph.ainvoke(
            {
                "messages": [
                    (
                        "user",
                        "Write only a short narrative for this envelope. It is not authoritative:\n"
                        + json.dumps(envelope),
                    )
                ]
            }
        )
        content = result["messages"][-1].content
        return content if isinstance(content, str) else json.dumps(content)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass


card = AgentCard(
    name="DiagnosticAgent",
    description="A LangGraph agent on Bedrock AgentCore",
    version="0.1.0",
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="tools",
            name="tools",
            description="Use tools to help answer questions",
            tags=["tools"],
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
    serve_a2a(LangGraphA2AExecutor(graph), card)
