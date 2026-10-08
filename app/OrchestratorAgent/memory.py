"""The narrow, Orchestrator-owned boundary around AgentCore Memory."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from typing import Any, Protocol


class InvestigationMemory(Protocol):
    """Memory is write-only for specialists; retrieval is planning-only."""

    async def retrieve_for_planning(self, context_id: str, query: str) -> list[dict[str, Any]]: ...

    async def write_turn(self, context_id: str, agent_name: str, content: dict[str, Any]) -> None: ...

    async def write_episode(self, context_id: str, outcome: dict[str, Any]) -> None: ...


class NoopInvestigationMemory:
    """Local/test default. Production enables the adapter with MEMORY_ID."""

    async def retrieve_for_planning(self, context_id: str, query: str) -> list[dict[str, Any]]:
        return []

    async def write_turn(self, context_id: str, agent_name: str, content: dict[str, Any]) -> None:
        return None

    async def write_episode(self, context_id: str, outcome: dict[str, Any]) -> None:
        return None


class AgentCoreInvestigationMemory:
    """AgentCore Memory data-plane adapter for the single-user RCA MVP.

    Events are durable inputs; summary and episode extraction remain eventually
    consistent server-side.  The adapter never exposes retrieval to specialists.
    """

    def __init__(self, memory_id: str, actor_id: str = "single-user", region_name: str | None = None):
        self.memory_id = memory_id
        self.actor_id = actor_id
        self.region_name = region_name

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> InvestigationMemory:
        environ = os.environ if environ is None else environ
        memory_id = environ.get("MEMORY_ID")
        if not memory_id:
            return NoopInvestigationMemory()
        return cls(memory_id, environ.get("MEMORY_ACTOR_ID", "single-user"), environ.get("AWS_REGION"))

    def _session(self, context_id: str):
        from bedrock_agentcore.memory import MemorySessionManager

        return MemorySessionManager(memory_id=self.memory_id, region_name=self.region_name).create_memory_session(
            self.actor_id, context_id
        )

    async def retrieve_for_planning(self, context_id: str, query: str) -> list[dict[str, Any]]:
        def retrieve() -> list[dict[str, Any]]:
            session = self._session(context_id)
            # The session summary lets a long Investigation continue without
            # resending history; episodes recall similar past RCAs.
            records: list[dict[str, Any]] = []
            for namespace in (
                f"investigations/{self.actor_id}/summaries/{context_id}",
                f"investigations/{self.actor_id}/episodes",
            ):
                found = session.search_long_term_memories(query=query, namespace_path=namespace)
                records.extend(dict(r.items()) if hasattr(r, "items") else dict(r) for r in found)
            return records

        return await asyncio.to_thread(retrieve)

    async def write_turn(self, context_id: str, agent_name: str, content: dict[str, Any]) -> None:
        def write() -> None:
            from bedrock_agentcore.memory.constants import ConversationalMessage, MessageRole

            message = json.dumps({"agent": agent_name, "content": content}, allow_nan=False)
            self._session(context_id).add_turns([
                ConversationalMessage(text=message, role=MessageRole.ASSISTANT)
            ])

        await asyncio.to_thread(write)

    async def write_episode(self, context_id: str, outcome: dict[str, Any]) -> None:
        # EPISODIC extraction is driven by the resolved synthesis event.  This
        # explicit marker makes completion eligibility auditable without adding
        # a second memory writer or a manual record API path.
        await self.write_turn(context_id, "orchestrator", {"past_rca_episode": outcome})
