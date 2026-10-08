"""Evidence Guard transport configuration."""
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

from specialist_a2a import SpecialistA2AAdapter


class EvidenceA2AAdapter(SpecialistA2AAdapter):
    url_environment = "EVIDENCE_AGENT_URL"
    jwt_environment = "EVIDENCE_AGENT_JWT"
    envelope_name = "evidence-envelope"

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[str | dict[str, Any]]:
        request = deepcopy(request)
        scope = request.get("scope")
        if isinstance(scope, dict) and "query" not in scope and "topic" in scope:
            # Previously persisted plans used topic; the live envelope uses query.
            scope["query"] = scope.pop("topic")
        async for event in super().stream(request):
            yield event
