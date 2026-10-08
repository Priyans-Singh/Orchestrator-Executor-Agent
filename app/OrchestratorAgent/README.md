# Orchestrator Investigation

The user-facing A2A endpoint accepts a text question, streams progress, and returns
one `investigation-synthesis` JSON artifact:

- `investigation_status`: `complete`, `partial`, `needs_clarification`, or `failed`.
- `findings`, `citations`, `context_snippets`: unchanged validated specialist results.
- `narrative`, `recommended_actions`, `clarifying_questions`: Orchestrator-authored.
- `overall_confidence`: minimum contributing finding confidence; `null` without findings.

Any clarification takes precedence over other specialist statuses. Otherwise a
failure makes the result failed, a partial makes it partial, and all complete
makes it complete. A partial specialist envelope requires a retry with explicit
best-effort confirmation. Invalid envelopes and specialist/model errors fail
closed without exposing provider exception text.

## Specialist transports

`Investigation` accepts an `Author` and named `Specialist` adapters. Specialists
stream progress strings followed by exactly one envelope. The default Diagnostic
adapter calls the live Diagnostic A2A runtime using `DIAGNOSTIC_AGENT_URL` and a
`DIAGNOSTIC_AGENT_JWT` bearer token. It maps the Investigation `task_id` and
`context_id` to the A2A message, relays only Diagnostic progress and its envelope,
and never lets the specialist address the user. It sets OpenTelemetry baggage
`context_id`; AgentCore instrumentation carries W3C trace headers. Trace fields do
not belong in delegation JSON.

The evidence adapter remains a clearly labelled synthetic fixture. It does not
access the web or AWS specialists, and is not real RCA evidence.

The tool-free LangGraph model authors plans, narrative, actions, and questions.
Code owns delegation order, status, confidence, validation, and copying results.
Diagnostics run before evidence when both are requested; standalone external
context never contributes confidence or recommended actions. Specialist narratives
are excluded from model input. No tools are bound to the Orchestrator model.

## Clarification

When the stream finishes in A2A `INPUT_REQUIRED`, send the answer as a new user
message using the same `task_id` and `context_id`. The executor reads its previous
plan and its prior Orchestrator-authored clarification from the synthesis artifact's
`investigation_state` metadata, retains the objective and specialist selection, and
re-delegates with `prior_context.answer`. The model updates scope from the answer and sets
`prior_context.continuation_confirmed` only for explicit best-effort permission.

State lives in the A2A task store, not an executor-local dictionary. A new executor
can resume an existing task; process-restart durability depends on the task store
configured by the hosting runtime.

## Run

```bash
uv sync --frozen
uv run python main.py
```

The endpoint serves A2A on port 9000. The default author uses Bedrock and needs
its usual IAM/model access. Configure `DIAGNOSTIC_AGENT_URL` to the deployed
Diagnostic A2A endpoint and `DIAGNOSTIC_AGENT_JWT` to a Cognito token accepted by
the shared CUSTOM_JWT authorizer. Example question: “Investigate revenue for
January 1–31, 2026 across all segments.”

## Shared Guardrail and event spans

Set `GUARDRAIL_ID` and `GUARDRAIL_VERSION` to the same Bedrock Guardrail policy
for every agent. Version defaults to `DRAFT`; use a published version for a
stable policy. Without an ID, local investigations skip Guardrail checks.
The runtime role needs `bedrock:ApplyGuardrail` access to that policy.

The Orchestrator checks the question before planning and its authored synthesis
before returning it. An intervention fails the investigation; blocked input
never reaches specialists and blocked synthesis is not released.

Each call emits a `guardrail.check` span within the current trace, covering the
Bedrock request. It records `guardrail.id`, `guardrail.version`, `guardrail.source`,
`guardrail.action`, `agent.name`, and `guardrail.triggered_policies` as a JSON
array of policy type/category/confidence objects. Confidence is included only
when Bedrock provides it; grounding scores are not relabelled as confidence.
Detected policies are included even when configured to observe rather than block.
Custom words, regexes, and denied topics use `CUSTOM_WORD`, `REGEX`, and `DENY`
labels so their configured strings cannot become span attributes.

Failed Bedrock checks propagate the failure and emit an error-status span with
action `ERROR` and no exception text. Neither flagged content, matches, response
output, nor provider error text is attached to this span.

`GuardrailPolicy.from_environment(agent_name=...)` reuses this check/span wiring
with a specialist's name and the same shared policy. Specialist runtime wiring
is deferred; issue #17's delivery boundary is the Orchestrator path.
LangGraph and default handoff/tool instrumentation remain in place. Business
traces remain unredacted and are restricted to the single-user secure
observability view described in ADR 004.

## Validate without AWS

From this directory:

```bash
uv run python -m unittest discover -s tests
uvx ty check investigation.py main.py author.py diagnostic_a2a.py specialists.py guardrail.py --python .venv/bin/python
```

Tests exercise the Investigation seam with offline adapters and exercise the live
Diagnostic transport through a recording A2A client. They require neither AWS
credentials nor a live Sheet, and cover initial calls, streamed progress,
clarification resume in a new executor, unchanged findings, minimum confidence,
failure handling, and evidence linkage.
