# Live specialist delegation

The default Orchestrator uses authenticated A2A clients for both specialists.
Configure these environment variables in the Orchestrator runtime:

| Specialist | Endpoint | CUSTOM_JWT bearer token |
| --- | --- | --- |
| Diagnostic analyst | `DIAGNOSTIC_AGENT_URL` | `DIAGNOSTIC_AGENT_JWT` |
| Evidence Guard | `EVIDENCE_AGENT_URL` | `EVIDENCE_AGENT_JWT` |

Tokens must be accepted by the specialists' shared CUSTOM_JWT authorizer.
Missing configuration fails the participating specialist; there is no synthetic
fallback. Local fixtures in `specialists.py` remain available for offline tests.

For Sheet plus web questions, the Orchestrator completes Diagnostic delegation
before passing its findings to Evidence Guard. A Sheet-only plan skips Evidence
Guard; a web-only plan sends an empty finding list and returns background snippets
with null overall confidence and no recommended actions. Citations retain the
specialist's provenance and finding links unchanged.

Both clients relay A2A progress and the named final envelope artifact, reuse the
Investigation task/context IDs, and close their client when the stream ends.
OpenTelemetry `context_id` baggage accompanies delegation; transport
instrumentation carries W3C trace headers. No trace ID is added to the payload.

These transport settings supersede the synthetic Evidence adapter description
in the earlier README. No live AWS integration is required by the offline suite:
recording A2A clients exercise the same adapters used in production.
