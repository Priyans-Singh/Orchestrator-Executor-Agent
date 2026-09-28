"""Investigation seam: specialist/model boundaries use offline adapters."""
import copy
import unittest

from investigation import Investigation


FINDINGS = [
    {"id": "strong", "claim": "Revenue fell", "metric": "revenue", "segment": None,
     "time_range": {"start": "2026-01-01", "end": "2026-01-31"}, "value": -12.0,
     "basis": "Performance!A1:D10", "source_pointer": "sheet://fixture",
     "confidence": 0.9, "assumptions": []},
    {"id": "weak", "claim": "Conversion fell", "metric": "conversion", "segment": None,
     "time_range": {"start": "2026-01-01", "end": "2026-01-31"}, "value": -3.0,
     "basis": "Performance!A1:D10", "source_pointer": "sheet://fixture",
     "confidence": 0.4, "assumptions": ["Small sample"]},
]


class SpecialistAdapter:
    def __init__(self, envelope):
        self.envelope = envelope
        self.requests = []

    async def stream(self, request):
        self.requests.append(copy.deepcopy(request))
        yield "Reading approved data."
        yield copy.deepcopy(self.envelope)


class AuthorAdapter:
    async def plan(self, question, previous):
        return {"objective": question, "scope": {"metric": "revenue"},
                "specialists": ["diagnostic"]}

    async def synthesize(self, evidence):
        assert "PRIVATE SPECIALIST TEXT" not in str(evidence)
        return {"narrative": "Revenue and conversion declined; the small sample limits certainty.",
                "recommended_actions": ["Validate the conversion sample before acting."],
                "clarifying_questions": []}


class InvestigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_progress_and_preserves_findings_with_minimum_confidence(self):
        specialist = SpecialistAdapter({"status": "complete", "findings": FINDINGS,
                                        "narrative": "PRIVATE SPECIALIST TEXT"})
        investigation = Investigation(AuthorAdapter(), {"diagnostic": specialist})
        events = [event async for event in investigation.stream(
            "Why did revenue fall?", "task-1", "context-1")]
        self.assertEqual("progress", events[0]["type"])
        self.assertIn("Reading approved data.", [e.get("message") for e in events])
        result = events[-1]["result"]
        self.assertEqual("complete", result["investigation_status"])
        self.assertEqual(FINDINGS, result["findings"])
        self.assertEqual(0.4, result["overall_confidence"])
        self.assertEqual("Revenue and conversion declined; the small sample limits certainty.", result["narrative"])
        self.assertEqual(["Validate the conversion sample before acting."], result["recommended_actions"])


class MemoryAdapter:
    def __init__(self, recalled=None):
        self.recalled = recalled or []
        self.retrieves = []
        self.turns = []
        self.episodes = []

    async def retrieve_for_planning(self, context_id, query):
        self.retrieves.append((context_id, query))
        return copy.deepcopy(self.recalled)

    async def write_turn(self, context_id, agent_name, content):
        self.turns.append((context_id, agent_name, copy.deepcopy(content)))

    async def write_episode(self, context_id, outcome):
        self.episodes.append((context_id, copy.deepcopy(outcome)))


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_orchestrator_retrieves_during_planning_and_all_turns_are_written(self):
        class Author(AuthorAdapter):
            async def plan(self, question, previous, recalled=None):
                self.recalled = recalled
                return await super().plan(question, previous)

        author = Author()
        diagnostic = SpecialistAdapter({"status": "complete", "findings": FINDINGS})
        memory = MemoryAdapter([{"content": "Similar RCA: pricing change", "score": 0.9}])
        events = [event async for event in Investigation(
            author, {"diagnostic": diagnostic}, memory=memory
        ).stream("Why did revenue fall?", "task-1", "context-1")]

        self.assertEqual([("context-1", "Why did revenue fall?")], memory.retrieves)
        self.assertEqual([{"content": "Similar RCA: pricing change", "score": 0.9}], author.recalled)
        self.assertEqual(["orchestrator", "diagnostic", "orchestrator"],
                         [turn[1] for turn in memory.turns])
        self.assertEqual("complete", memory.episodes[0][1]["investigation_status"])
        self.assertEqual("complete", events[-1]["result"]["investigation_status"])

    async def test_only_complete_or_partial_investigations_create_episodes(self):
        for status in ("needs_clarification", "failed"):
            with self.subTest(status=status):
                memory = MemoryAdapter()
                specialist = SpecialistAdapter({"status": status, "findings": [],
                                                "clarifying_questions": ["What dates?"]
                                                if status == "needs_clarification" else []})
                events = [event async for event in Investigation(
                    AuthorAdapter(), {"diagnostic": specialist}, memory=memory
                ).stream("Why?", "t", "c")]
                self.assertEqual(status, events[-1]["result"]["investigation_status"])
                self.assertEqual([], memory.episodes)

    async def test_partial_investigation_creates_an_episode(self):
        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {"metric": "revenue"},
                        "specialists": ["diagnostic"], "continuation_confirmed": True}

        memory = MemoryAdapter()
        events = [event async for event in Investigation(Author(), {
            "diagnostic": SpecialistAdapter({"status": "partial", "findings": FINDINGS})
        }, memory=memory).stream("Proceed", "t", "c", {"objective": "Original", "specialists": ["diagnostic"]})]
        self.assertEqual("partial", events[-1]["result"]["investigation_status"])
        self.assertEqual(1, len(memory.episodes))


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_clarification_wins_over_failure_and_is_authored_by_orchestrator(self):
        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {}, "specialists": ["diagnostic", "evidence"]}

            async def synthesize(self, evidence):
                return {"narrative": "I need the reporting period before I can continue.",
                        "recommended_actions": [],
                        "clarifying_questions": ["Which reporting period should I investigate?"]}

        investigation = Investigation(Author(), {
            "diagnostic": SpecialistAdapter({"status": "failed", "findings": []}),
            "evidence": SpecialistAdapter({"status": "needs_clarification", "citations": [],
                                             "clarifying_questions": ["RAW QUESTION"]})})
        events = [e async for e in investigation.stream("Why?", "t", "c")]
        self.assertEqual("needs_clarification", events[-1]["result"]["investigation_status"])
        self.assertEqual(["Which reporting period should I investigate?"],
                         events[-1]["result"]["clarifying_questions"])
        self.assertIsNone(events[-1]["result"]["overall_confidence"])

    async def test_failure_and_partial_never_roll_up_to_complete(self):
        for status, prior in [("failed", None), ("partial", None)]:
            with self.subTest(status=status):
                investigation = Investigation(AuthorAdapter(), {"diagnostic": SpecialistAdapter(
                    {"status": status, "findings": []})})
                events = [e async for e in investigation.stream("Why?", "t", "c", prior)]
                self.assertNotEqual("complete", events[-1]["result"]["investigation_status"])


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_preserves_identity_objective_and_passes_answer_as_prior_context(self):
        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {"metric": "revenue"},
                        "specialists": ["diagnostic"],
                        "continuation_confirmed": bool(previous)}

            async def synthesize(self, evidence):
                return {"narrative": "I need your reporting dates.", "recommended_actions": [],
                        "clarifying_questions": ["What dates should I use?"]}

        specialist = SpecialistAdapter({"status": "needs_clarification", "findings": [],
                                        "clarifying_questions": ["start/end?"]})
        investigation = Investigation(Author(), {"diagnostic": specialist})
        first = [e async for e in investigation.stream("Investigate revenue", "t", "c")]
        specialist.envelope = {"status": "partial", "findings": FINDINGS}
        second = [e async for e in investigation.stream(
            "Proceed best-effort without dates", "t", "c", first[-1]["state"])]
        request = specialist.requests[-1]
        self.assertEqual("t", request["task_id"])
        self.assertEqual("c", request["context_id"])
        self.assertEqual("Investigate revenue", request["objective"])
        self.assertEqual("Proceed best-effort without dates", request["prior_context"]["answer"])
        self.assertTrue(request["prior_context"]["continuation_confirmed"])
        self.assertEqual("partial", second[-1]["result"]["investigation_status"])

    async def test_partial_requires_retry_with_explicit_continuation_confirmation(self):
        specialist = SpecialistAdapter({"status": "partial", "findings": FINDINGS})
        events = [e async for e in Investigation(AuthorAdapter(), {"diagnostic": specialist}).stream(
            "Why?", "t", "c")]
        self.assertEqual("failed", events[-1]["result"]["investigation_status"])
        self.assertEqual([], events[-1]["result"]["findings"])


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_specialist_output_and_exceptions_fail_closed(self):
        bad_confidence = copy.deepcopy(FINDINGS)
        bad_confidence[0]["confidence"] = float("nan")
        for envelope in [{"status": "invented", "findings": []},
                         {"status": "complete", "findings": bad_confidence},
                         {"status": "complete", "findings": [{"confidence": 0.8}]}]:
            with self.subTest(envelope=envelope):
                events = [e async for e in Investigation(AuthorAdapter(), {
                    "diagnostic": SpecialistAdapter(envelope)}).stream("Why?", "t", "c")]
                self.assertEqual("failed", events[-1]["result"]["investigation_status"])
                self.assertEqual([], events[-1]["result"]["findings"])

        class BrokenSpecialist:
            async def stream(self, request):
                raise RuntimeError("private credentials or provider error")
                yield

        events = [e async for e in Investigation(AuthorAdapter(), {
            "diagnostic": BrokenSpecialist()}).stream("Why?", "t", "c")]
        self.assertEqual("failed", events[-1]["result"]["investigation_status"])
        self.assertNotIn("private credentials", str(events))

    async def test_invalid_user_input_is_rejected_without_delegation(self):
        for question in [None, 42, [], {}, "", "   "]:
            specialist = SpecialistAdapter({"status": "complete", "findings": FINDINGS})
            events = [e async for e in Investigation(AuthorAdapter(), {
                "diagnostic": specialist}).stream(question, "t", "c")]
            self.assertEqual("failed", events[-1]["result"]["investigation_status"])
            self.assertEqual([], specialist.requests)

    async def test_model_cannot_overwrite_computed_fields_or_mutate_evidence(self):
        class Author(AuthorAdapter):
            async def synthesize(self, evidence):
                evidence["findings"][0]["confidence"] = 1.0
                return {"narrative": "My synthesis", "recommended_actions": [],
                        "clarifying_questions": [], "overall_confidence": 1,
                        "findings": [], "investigation_status": "failed"}

        events = [e async for e in Investigation(Author(), {"diagnostic": SpecialistAdapter(
            {"status": "complete", "findings": FINDINGS})}).stream("Why?", "t", "c")]
        self.assertEqual(FINDINGS, events[-1]["result"]["findings"])
        self.assertEqual(0.4, events[-1]["result"]["overall_confidence"])
        self.assertEqual("complete", events[-1]["result"]["investigation_status"])


CITATION = {"url": "https://example.org/report", "title": "Report", "publishedDate": None,
            "snippet": "Demand softened", "reputation_tier": "general",
            "retrieved_at": "2026-01-31T12:00:00Z", "query": "demand",
            "corroborates_finding_id": ["strong"], "challenges_finding_id": []}


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_diagnostic_precedes_evidence_and_citations_stay_unmodified(self):
        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {}, "specialists": ["evidence", "diagnostic"]}

        calls = []

        class OrderedSpecialist(SpecialistAdapter):
            def __init__(self, name, envelope):
                super().__init__(envelope)
                self.name = name

            async def stream(self, request):
                calls.append(self.name)
                async for event in super().stream(request):
                    yield event

        evidence = OrderedSpecialist("evidence", {"status": "complete", "citations": [CITATION]})
        events = [e async for e in Investigation(Author(), {
            "diagnostic": OrderedSpecialist("diagnostic", {"status": "complete", "findings": FINDINGS}),
            "evidence": evidence}).stream("Why?", "t", "c")]
        self.assertEqual(["diagnostic", "evidence"], calls)
        self.assertEqual(FINDINGS, evidence.requests[0]["scope"]["findings"])
        self.assertEqual([CITATION], events[-1]["result"]["citations"])
        self.assertEqual(0.4, events[-1]["result"]["overall_confidence"])

    async def test_sheet_only_plan_skips_evidence_guard(self):
        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {"metric": "revenue"},
                        "specialists": ["diagnostic"]}

        evidence = SpecialistAdapter({"status": "complete", "context_snippets": []})
        events = [e async for e in Investigation(Author(), {
            "diagnostic": SpecialistAdapter({"status": "complete", "findings": FINDINGS}),
            "evidence": evidence}).stream("Why did revenue fall?", "t", "c")]
        self.assertEqual([], evidence.requests)
        self.assertEqual(FINDINGS, events[-1]["result"]["findings"])

    async def test_standalone_context_is_not_rca_evidence_or_action_justification(self):
        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {}, "specialists": ["evidence"]}

        snippet = {k: v for k, v in CITATION.items() if not k.endswith("finding_id")}
        events = [e async for e in Investigation(Author(), {"evidence": SpecialistAdapter(
            {"status": "complete", "context_snippets": [snippet]})}).stream("External context?", "t", "c")]
        result = events[-1]["result"]
        self.assertEqual([snippet], result["context_snippets"])
        self.assertEqual([], result["findings"])
        self.assertEqual([], result["recommended_actions"])
        self.assertIsNone(result["overall_confidence"])

    async def test_citation_cannot_reference_an_unknown_finding(self):
        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "scope": {}, "specialists": ["evidence"]}

        events = [e async for e in Investigation(Author(), {"evidence": SpecialistAdapter(
            {"status": "complete", "citations": [CITATION]})}).stream("External context?", "t", "c")]
        self.assertEqual("failed", events[-1]["result"]["investigation_status"])
        self.assertEqual([], events[-1]["result"]["citations"])


class DefaultAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_bundled_diagnostic_adapter_answers_known_fixture_without_aws(self):
        from specialists import DiagnosticAdapter

        class Author(AuthorAdapter):
            async def plan(self, question, previous):
                return {"objective": question, "specialists": ["diagnostic"],
                        "scope": {"metric": "revenue", "time_range": {
                            "start": "2026-01-01", "end": "2026-01-31"}}}

        events = [e async for e in Investigation(Author(), {"diagnostic": DiagnosticAdapter()}).stream(
            "Investigate January revenue", "t", "c")]
        result = events[-1]["result"]
        self.assertEqual("complete", result["investigation_status"])
        self.assertEqual(-12.0, result["findings"][0]["value"])
        self.assertIn("synthetic", result["findings"][0]["basis"].lower())


if __name__ == "__main__":
    unittest.main()
