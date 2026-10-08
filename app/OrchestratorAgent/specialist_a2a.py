"""Authenticated specialist transport for the Investigation seam."""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import json
import os
from typing import Any

from a2a.client import ClientConfig, ClientFactory
from a2a.helpers import get_artifact_text, get_message_text, new_text_message
from a2a.types import Role, SendMessageRequest
from opentelemetry import baggage, context as otel_context


Connect = Callable[[str, str], Awaitable[Any]]


async def _connect(url: str, bearer_token: str) -> Any:
    """Create an authenticated A2A client from a specialist agent card."""
    import httpx

    http_client = httpx.AsyncClient(headers={"Authorization": f"Bearer {bearer_token}"})
    try:
        return await ClientFactory(ClientConfig(httpx_client=http_client)).create_from_url(url)
    except Exception:
        await http_client.aclose()
        raise


class SpecialistA2AAdapter:
    """Relay one specialist A2A stream as Investigation events.

    W3C trace headers are injected by AgentCore's OpenTelemetry HTTP
    instrumentation. This adapter sets the cross-agent ``context_id`` baggage
    key around the outbound call; correlation deliberately stays out of the
    delegation payload.
    """

    url_environment: str
    jwt_environment: str
    envelope_name: str

    def __init__(self, url: str | None = None, bearer_token: str | None = None,
                 connect: Connect = _connect):
        self.url = url if url is not None else os.environ.get(self.url_environment)
        self.bearer_token = (bearer_token if bearer_token is not None
                             else os.environ.get(self.jwt_environment))
        self.connect = connect

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[str | dict[str, Any]]:
        task_id = request.get("task_id")
        context_id = request.get("context_id")
        if not isinstance(task_id, str) or not task_id or not isinstance(context_id, str) or not context_id:
            raise ValueError("Specialist delegation requires task_id and context_id")
        if not self.url or not self.bearer_token:
            raise RuntimeError("Specialist A2A URL and CUSTOM_JWT token must be configured")

        token = otel_context.attach(baggage.set_baggage("context_id", context_id))
        client = None
        received_envelope = False
        try:
            client = await self.connect(self.url, self.bearer_token)
            message = new_text_message(
                json.dumps(request, allow_nan=False), task_id=task_id,
                context_id=context_id, role=Role.ROLE_USER,
            )
            async for response in client.send_message(SendMessageRequest(message=message)):
                if response.HasField("status_update"):
                    status = response.status_update.status
                    if status.HasField("message"):
                        progress = get_message_text(status.message)
                        if progress:
                            yield progress
                if response.HasField("artifact_update"):
                    artifact = response.artifact_update.artifact
                    if artifact.name == self.envelope_name:
                        envelope = json.loads(get_artifact_text(artifact))
                        if not isinstance(envelope, dict):
                            raise ValueError("Specialist A2A artifact must contain a JSON object")
                        received_envelope = True
                        yield envelope
            if not received_envelope:
                raise ValueError("Specialist A2A response did not include an envelope")
        finally:
            otel_context.detach(token)
            if client is not None:
                await client.close()
