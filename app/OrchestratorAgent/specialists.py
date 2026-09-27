"""Local synthetic specialists for the adapter-only Investigation milestone.

These adapters perform no Sheet reads or web searches. Replace them through
Investigation's Specialist interface when live specialist transport is added.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class DiagnosticAdapter:
    async def stream(self, request: dict[str, Any]) -> AsyncIterator[str | dict[str, Any]]:
        yield "Checking the synthetic diagnostic fixture (no live Sheet access)."
        scope = request["scope"]
        period = {"start": "2026-01-01", "end": "2026-01-31"}
        if (scope.get("metric") != "revenue" or scope.get("time_range") != period
                or scope.get("segment") is not None):
            yield {"status": "needs_clarification", "findings": [], "narrative": None,
                   "clarifying_questions": [
                       "This adapter only has synthetic, all-segment revenue for January 2026. "
                       "Would you like to investigate that fixture?"]}
            return
        yield {"status": "complete", "clarifying_questions": [], "narrative": None,
               "findings": [{
                   "id": "synthetic-revenue-202601", "metric": "revenue", "segment": None,
                   "time_range": period, "claim": "Synthetic revenue declined 12% from December.",
                   "value": -12.0, "basis": "Synthetic fixture: December=100, January=88; percent change.",
                   "source_pointer": "fake-sheet://revenue/2026-01", "confidence": 0.6,
                   "assumptions": ["Demonstration data only; no production Sheet was read."],
               }]}


class EvidenceAdapter:
    async def stream(self, request: dict[str, Any]) -> AsyncIterator[str | dict[str, Any]]:
        yield "Checking the synthetic evidence fixture (no live web search)."
        snippet = {"url": "https://example.invalid/synthetic-report", "title": "Synthetic demand report",
                   "publishedDate": "2026-01-31", "snippet": "Synthetic context: demand softened in January.",
                   "reputation_tier": "general", "retrieved_at": "2026-02-01T00:00:00Z",
                   "query": "synthetic January demand fixture"}
        findings = request["scope"].get("findings", [])
        if findings:
            snippet["corroborates_finding_id"] = [finding["id"] for finding in findings]
            yield {"status": "complete", "citations": [snippet], "narrative": None}
        else:
            yield {"status": "complete", "context_snippets": [snippet], "narrative": None}
