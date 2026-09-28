"""Investigation policy, independent of model and specialist transports."""
from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from math import isfinite
from typing import Any, Protocol

from memory import InvestigationMemory, NoopInvestigationMemory


class Specialist(Protocol):
    def stream(self, request: dict[str, Any]) -> AsyncIterator[str | dict[str, Any]]: ...


class Author(Protocol):
    async def plan(self, question: str, previous: dict[str, Any] | None,
                   recalled: list[dict[str, Any]] | None = None) -> dict[str, Any]: ...

    async def synthesize(self, evidence: dict[str, Any]) -> dict[str, Any]: ...


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(s, str) and s.strip() for s in value)


def _validate_envelope(envelope: dict[str, Any], prior: dict[str, Any]) -> None:
    if envelope.get("status") not in {"complete", "partial", "needs_clarification", "failed"}:
        raise ValueError("Unknown specialist status")
    if envelope["status"] == "partial" and prior.get("continuation_confirmed") is not True:
        raise ValueError("Best-effort requires confirmed continuation")
    if not _strings(envelope.get("clarifying_questions", [])):
        raise ValueError("Invalid clarification questions")
    findings = envelope.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("Invalid findings")
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("Invalid finding")
        for field in ("id", "claim", "metric", "basis"):
            if not isinstance(finding.get(field), str) or not finding[field].strip():
                raise ValueError("Missing finding field")
        confidence = finding.get("confidence")
        value = finding.get("value")
        if type(confidence) not in (int, float) or type(value) not in (int, float):
            raise ValueError("Invalid finding value/confidence")
        assert isinstance(confidence, (int, float))
        assert isinstance(value, (int, float))
        if not isfinite(confidence) or not 0 <= confidence <= 1 or not isfinite(value):
            raise ValueError("Invalid finding value/confidence")
        if ("segment" not in finding or finding["segment"] is not None
                and not isinstance(finding["segment"], str)):
            raise ValueError("Invalid segment")
        if not isinstance(finding.get("time_range"), dict) or not _strings(finding.get("assumptions")):
            raise ValueError("Invalid finding scope/assumptions")



def _validate_results(envelope: dict[str, Any], name: str, findings: list[dict[str, Any]]) -> None:
    arrays = [key for key in ("findings", "citations", "context_snippets") if key in envelope]
    expected = "findings" if name == "diagnostic" else "citations" if findings else "context_snippets"
    # Empty citation arrays on clarification/failure carry no evidence.
    if envelope["status"] in {"needs_clarification", "failed"}:
        if any(envelope.get(key) for key in arrays):
            raise ValueError("Non-result status carried results")
        return
    if arrays != [expected] or not isinstance(envelope[expected], list):
        raise ValueError("Incorrect specialist result array")
    ids = {finding["id"] for finding in findings}
    for item in envelope.get("citations", []) + envelope.get("context_snippets", []):
        if not isinstance(item, dict):
            raise ValueError("Invalid external context")
        for field in ("url", "title", "snippet", "retrieved_at", "query"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError("Missing external context field")
        if item.get("reputation_tier") not in {"trusted", "general"} or "publishedDate" not in item:
            raise ValueError("Invalid external context provenance")
        links = []
        for field in ("corroborates_finding_id", "challenges_finding_id"):
            if not _strings(item.get(field, [])):
                raise ValueError("Invalid finding links")
            links.extend(item.get(field, []))
        if expected == "citations" and (not links or not set(links) <= ids):
            raise ValueError("Citation must link to a contributing finding")
        if expected == "context_snippets" and links:
            raise ValueError("Standalone context cannot link to findings")


def _empty_result(narrative: str) -> dict[str, Any]:
    return {"investigation_status": "failed", "findings": [], "citations": [],
            "context_snippets": [], "overall_confidence": None,
            "narrative": narrative, "recommended_actions": [], "clarifying_questions": []}


class Investigation:
    def __init__(self, author: Author, specialists: dict[str, Specialist],
                 memory: InvestigationMemory | None = None):
        self.author = author
        self.specialists = specialists
        self.memory = memory or NoopInvestigationMemory()

    async def _write_memory_turn(self, context_id: str, agent_name: str, content: dict[str, Any]) -> None:
        try:
            await self.memory.write_turn(context_id, agent_name, deepcopy(content))
        except Exception:
            # Memory extraction is asynchronous and deliberately non-load-bearing.
            return

    async def stream(self, question: str, task_id: str, context_id: str,
                     previous: dict[str, Any] | None = None) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "progress", "message": "Planning the investigation."}
        if not isinstance(question, str) or not question.strip():
            yield {"type": "result", "result": _empty_result("Please provide a non-empty text question."),
                   "state": None}
            return
        try:
            recalled = await self.memory.retrieve_for_planning(context_id, question)
            try:
                plan = await self.author.plan(question, deepcopy(previous), deepcopy(recalled))
            except TypeError:
                # Preserves the established two-argument Author adapter seam.
                plan = await self.author.plan(question, deepcopy(previous))
            if previous:
                plan["objective"] = previous["objective"]
                plan["specialists"] = previous["specialists"]
            if (not isinstance(plan.get("objective"), str) or not plan["objective"].strip()
                    or not isinstance(plan.get("scope"), dict)
                    or not _strings(plan.get("specialists")) or not plan["specialists"]
                    or any(name not in self.specialists for name in plan["specialists"])):
                raise ValueError("Invalid plan")
        except Exception:
            yield {"type": "result", "result": _empty_result("I could not plan this investigation. Please retry."),
                   "state": previous}
            return
        await self._write_memory_turn(context_id, "orchestrator", {
            "question": question, "plan": plan, "recalled_past_rcas": recalled,
        })
        prior = ({"answer": question, "continuation_confirmed": plan.get("continuation_confirmed") is True}
                 if previous else {})
        findings: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        snippets: list[dict[str, Any]] = []
        statuses: list[str] = []
        questions: list[str] = []
        for name in sorted(set(plan["specialists"]), key=lambda name: name != "diagnostic"):
            request = {"task_id": task_id, "context_id": context_id,
                       "objective": plan["objective"], "scope": deepcopy(plan["scope"]),
                       "prior_context": prior}
            if name == "evidence":
                request["scope"]["findings"] = deepcopy(findings)
            envelope: dict[str, Any] | None = None
            try:
                async for event in self.specialists[name].stream(request):
                    if isinstance(event, str):
                        yield {"type": "progress", "message": event}
                    else:
                        if envelope is not None:
                            raise ValueError("Multiple specialist envelopes")
                        _validate_envelope(event, prior)
                        _validate_results(event, name, findings)
                        envelope = deepcopy(event)
                if envelope is None:
                    raise ValueError("Missing specialist envelope")
            except Exception:
                envelope = {"status": "failed", "findings": []}
            findings.extend(envelope.get("findings", []))
            citations.extend(envelope.get("citations", []))
            snippets.extend(envelope.get("context_snippets", []))
            statuses.append(envelope["status"])
            questions.extend(envelope.get("clarifying_questions", []))
            await self._write_memory_turn(context_id, name, envelope)
        status = ("needs_clarification" if "needs_clarification" in statuses else
                  "failed" if "failed" in statuses else
                  "partial" if "partial" in statuses else "complete")
        result = {"investigation_status": status, "findings": findings,
                  "citations": citations, "context_snippets": snippets,
                  "overall_confidence": min((f["confidence"] for f in findings), default=None)}
        yield {"type": "progress", "message": "Synthesizing the investigation."}
        try:
            authored = await self.author.synthesize(deepcopy({
                **result, "objective": plan["objective"], "specialist_questions": questions}))
            if (not isinstance(authored.get("narrative"), str) or not authored["narrative"].strip()
                    or not _strings(authored.get("recommended_actions"))
                    or not _strings(authored.get("clarifying_questions"))
                    or status == "needs_clarification" and not authored["clarifying_questions"]):
                raise ValueError("Invalid synthesis")
            for field in ("narrative", "recommended_actions", "clarifying_questions"):
                result[field] = authored[field]
        except Exception:
            result.update(narrative="I could not finish writing the investigation. Please retry.",
                          recommended_actions=[], clarifying_questions=[])
            if status == "needs_clarification":
                result.update(narrative="I need more information to continue this investigation.",
                              clarifying_questions=["Please clarify the metric, reporting dates, or scope of your question."])
            else:
                result["investigation_status"] = "failed"
        if not findings:
            result["recommended_actions"] = []
        await self._write_memory_turn(context_id, "orchestrator", {"synthesis": result})
        if result["investigation_status"] in {"complete", "partial"}:
            try:
                await self.memory.write_episode(context_id, deepcopy(result))
            except Exception:
                pass
        state = deepcopy(plan)
        if status == "needs_clarification":
            state["previous_clarification"] = {
                "narrative": result["narrative"],
                "questions": result["clarifying_questions"],
            }
        yield {"type": "result", "result": result, "state": state}
