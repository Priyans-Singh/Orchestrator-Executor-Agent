# ADR 007: Evidence Guard reputation tiers via dual gateway queries, not computed scores

**Status:** Accepted

## Context

ADR 004 committed to source-reputation scoring and citations for external web
content, without settling a mechanism. The Web Search Tool gateway connector
(ADR 006) returns only `url`, `title`, `publishedDate`, and a text snippet per
result — no reputation signal of its own. It does support a target-level
domain exclude/include list (enforced before results return, hidden from the
agent) and, from connector version 1.2.0, a per-request `domainFilter`.

The alternatives were: compute a heuristic or LLM-judged score per result at
runtime inside Evidence Guard, or keep all scoring logic out of the agent and
rely entirely on the connector's domain-list filtering.

## Decision

Two reputation tiers only: `trusted` and `general`. No numeric score, no
per-result runtime computation, no LLM judgment.

A version-controlled policy file, `docs/evidence-reputation.yaml`, holds two
lists — a **hard denylist** (wired into the Gateway target config, so the
connector blocks these domains before results are ever returned, mirroring
the Data Gateway's reject-before-contacting-the-source pattern) and a
**trusted-domain allowlist** (used as a request-level filter).

Every Evidence Guard search issues two `tools/call` invocations to the Web
Search Tool target: one unrestricted (still bounded by the target's hard
denylist) and one with `filters.domainFilter.include` set to the
trusted-domain list. A result's tier is simply which call returned it — tier
assignment requires no scoring code. If the same URL appears in both passes,
keep one citation labeled `trusted`. Nothing surviving the hard denylist is
ever silently dropped; every result is surfaced as external context with its
tier label.

Each external Evidence Citation carries: `url`, `title`, `publishedDate`
(nullable), a quoted `snippet`, `reputation_tier`, a `retrieved_at` timestamp,
and the search `query` used.

Evidence Guard's output schema keeps internal findings and external citations
as separate structures. Every external citation carries a required,
non-empty array of finding-link ids (`corroborates_finding_id` /
`challenges_finding_id`, may reference more than one finding) — there is no
schema slot for a standalone external claim, so ADR 004's "external content
cannot establish a primary root-cause claim" is enforced by the output shape,
not by prompting alone.

## Consequences

- Every Evidence Guard web search costs two gateway tool calls instead of
  one, always, regardless of whether the trusted-only pass turns up anything.
- `docs/evidence-reputation.yaml` becomes a second policy file alongside
  `docs/data-contract.yaml`, with its own review discipline; growing the
  trusted list is a config change, not a code change.
- Reputation is only as good as the curated domain list — there's no
  per-result fallback (heuristic or LLM) for domains that are neither
  denylisted nor trusted; they always land as `general`.

**Amended by ADR 008:** this ADR assumed Evidence Guard always runs after the
Diagnostic analyst. When Evidence Guard runs standalone (no findings to link
against), it returns a distinct `context_snippets[]` type instead of
`citations[]` — the finding-link requirement above still holds for every
actual citation.
