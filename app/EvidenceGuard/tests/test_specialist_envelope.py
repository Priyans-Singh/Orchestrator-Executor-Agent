"""Evidence Guard behavior at the specialist-envelope seam."""
from __future__ import annotations

import unittest

from specialist_envelope import build_evidence_envelope


TRUSTED = "https://www.bls.gov/news.release/empsit.nr0.htm"
GENERAL = "https://industry.example/report"
BLOCKED = "https://spam.example/misleading-report"
FINDING = {"id": "finding-revenue-jan"}


class SearchFixture:
    """Gateway boundary fixture; each invocation returns a distinct pass."""

    def __init__(self):
        self.calls = []

    def __call__(self, query, filters=None):
        self.calls.append({"query": query, "filters": filters})
        if filters is None:
            return [
                {"url": GENERAL, "title": "Industry report", "publishedDate": None,
                 "snippet": "Demand softened in January."},
                {"url": TRUSTED, "title": "Employment Situation", "publishedDate": "2026-02-06",
                 "snippet": "Official labor-market release."},
                {"url": BLOCKED, "title": "Spam", "publishedDate": "2026-02-01",
                 "snippet": "Do not surface this."},
            ]
        return [
            {"url": TRUSTED, "title": "Employment Situation", "publishedDate": "2026-02-06",
             "snippet": "Official labor-market release."},
        ]


def request(findings):
    return {
        "task_id": "task-001", "context_id": "investigation-001",
        "objective": "Check whether external context supports the January revenue finding.",
        "scope": {"query": "January 2026 demand context", "findings": findings},
    }


class EvidenceEnvelopeTests(unittest.TestCase):
    def test_a_failed_unrestricted_pass_does_not_skip_the_required_trusted_pass(self):
        class FailingFirstPass:
            def __init__(self):
                self.calls = []

            def __call__(self, query, filters=None):
                self.calls.append(filters)
                if filters is None:
                    raise ValueError("temporary gateway failure")
                return []

        gateway = FailingFirstPass()

        envelope = build_evidence_envelope(request([]), gateway)

        self.assertEqual("failed", envelope["status"])
        self.assertEqual(2, len(gateway.calls))

    def test_dual_search_deduplicates_to_trusted_and_preserves_general_results(self):
        gateway = SearchFixture()

        envelope = build_evidence_envelope(
            request([FINDING]), gateway, retrieved_at="2026-02-07T00:00:00Z"
        )

        self.assertEqual("complete", envelope["status"])
        self.assertEqual(2, len(gateway.calls))
        self.assertEqual("January 2026 demand context", gateway.calls[0]["query"])
        self.assertIsNone(gateway.calls[0]["filters"])
        self.assertIn("include", gateway.calls[1]["filters"]["domainFilter"])
        citations = {item["url"]: item for item in envelope["citations"]}
        self.assertEqual({GENERAL, TRUSTED}, set(citations))
        self.assertEqual("general", citations[GENERAL]["reputation_tier"])
        self.assertEqual("trusted", citations[TRUSTED]["reputation_tier"])
        self.assertEqual([FINDING["id"]], citations[GENERAL]["corroborates_finding_id"])
        self.assertEqual([], citations[GENERAL]["challenges_finding_id"])
        self.assertEqual("2026-02-07T00:00:00Z", citations[GENERAL]["retrieved_at"])
        self.assertEqual("January 2026 demand context", citations[GENERAL]["query"])

    def test_denylisted_results_never_appear_even_if_a_gateway_fixture_returns_one(self):
        envelope = build_evidence_envelope(request([FINDING]), SearchFixture())

        self.assertNotIn(BLOCKED, [citation["url"] for citation in envelope["citations"]])

    def test_findings_produce_linked_citations_only(self):
        envelope = build_evidence_envelope(request([FINDING]), SearchFixture())

        self.assertIn("citations", envelope)
        self.assertNotIn("context_snippets", envelope)
        for citation in envelope["citations"]:
            self.assertTrue(citation["corroborates_finding_id"] or citation["challenges_finding_id"])

    def test_empty_findings_produce_unlinked_context_snippets_only(self):
        envelope = build_evidence_envelope(request([]), SearchFixture())

        self.assertIn("context_snippets", envelope)
        self.assertNotIn("citations", envelope)
        for snippet in envelope["context_snippets"]:
            self.assertNotIn("corroborates_finding_id", snippet)
            self.assertNotIn("challenges_finding_id", snippet)


if __name__ == "__main__":
    unittest.main()
