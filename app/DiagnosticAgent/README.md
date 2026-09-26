# DiagnosticAgent

An A2A (Agent-to-Agent) agent deployed on Amazon Bedrock AgentCore using LangChain + LangGraph.

## Overview

This agent implements the A2A protocol using LangGraph, enabling agent-to-agent communication.

## Delegation contract

The agent accepts one JSON A2A delegation request in its user text. It requires
`task_id`, `context_id`, a non-empty `objective`, and a `scope`. A complete
scope has a non-empty `metric` plus an ISO-8601 `time_range` with `start` and
`end`; `segment` is optional. Incomplete first passes return
`needs_clarification`. A `partial` result is only possible when
`prior_context.continuation_confirmed` is `true` and a metric is available.

The final A2A artifact is one JSON specialist envelope. Its findings are
deterministic fake-adapter data for this ticket; no Google Sheets data is read.
The Bedrock model contributes only the optional `narrative`, which is never
load-bearing. Progress status updates precede the final artifact.

## Local Development

```bash
uv sync
uv run python main.py
```

The agent starts on port 9000.

Run the envelope tests (including the default real-Bedrock integration test):

```bash
UV_CACHE_DIR=/tmp/diagnostic-agent-uv-cache uv run python -m unittest discover -s tests
```

## Deploy

```bash
agentcore deploy
```
