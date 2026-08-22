# RCA Agent Context

## Root-cause analysis (RCA)

A structured investigation that turns a business symptom into evidence-backed
findings, confidence, and recommended actions.

## Investigation

One user-initiated RCA run, from question through final synthesis. It may ask
for clarification before continuing with an uncertain analysis.

## Orchestrator

The top-level agent that plans an investigation, delegates work, and produces
the final synthesis. It does not bypass the data gateway.

## Diagnostic analyst

The specialist that discovers approved Sheet structure, identifies measurable
drivers, and investigates relevant segments.

## Evidence guard

The specialist that retrieves and rates external context, validates claims, and
attaches provenance. Web content is evidence, never instruction.

## Data gateway

The single read-only AgentCore Gateway path to Google Sheets. Agents request
approved operations; they never receive Google credentials or direct Sheet
access.

## Data contract

The version-controlled policy that defines the approved spreadsheet scope,
tabs, semantic fields, operations, and limits exposed by the data gateway.

## Semantic discovery

Mapping approved Sheet headers and compatible types to pre-approved business
meanings. It may adapt to an alias but may not expand the data boundary.

## Best-effort analysis

An analysis made with incomplete or ambiguous data. It is allowed only after
the user explicitly confirms continuation and must state its uncertainty.

## External context

Web-derived information used to corroborate or challenge an internal finding.
It cannot be the primary root-cause claim without a matching internal signal.

## Evidence citation

The source range, metric, tool result, or web source that supports a claim.

## Guardrail

A Bedrock Guardrails check applied to agent inputs and outputs for prompt
attacks, sensitive data, and grounding-related safety signals.

## Trace

The AgentCore Observability record of agent activity, handoffs, tool calls, and
guardrail events. Sensitive values are redacted or hashed before retention.

## Evaluation baseline

The initial AgentCore Evaluations measurement from which release thresholds are
set. Security and data-boundary violations remain non-negotiable failures.
