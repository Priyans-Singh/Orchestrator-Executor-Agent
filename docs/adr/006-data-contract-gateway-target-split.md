# ADR 006: Split the Data Gateway into a Sheets-read target and a math-ops target, and fix the data contract to one sheet

**Status:** Accepted

## Context

ADR 002 committed to a single AgentCore Gateway as the only path to Google
Sheets, with a version-controlled policy limiting scope, tabs, semantic
fields, operations, and query limits. That policy still needed a concrete
shape: which Gateway target type to use, what operations to expose, how
computation over Sheet data should happen, how the policy is stored, and
whether the MVP should support one fixed sheet or a sheet supplied per end
user.

AgentCore Gateway's only built-in connectors are Amazon Bedrock Knowledge
Bases and the Web Search Tool — there is no built-in Google Sheets connector.
Of the remaining target types, only `openApiSchema` supports OAuth
Authorization Code (3LO) outbound auth, the flow that produces the
per-user-owned, narrowly scoped refresh token ADR 002 already assumes.
`lambdaFunctionArn` targets only support IAM outbound auth.

## Decision

Use two Gateway targets under the same single Gateway:

- **Sheets-read target** (`openApiSchema`, Google Sheets API v4 spec, OAuth
  Authorization Code outbound auth via a named credential provider). Exposes
  exactly two operations: `get-metadata` (tab/header discovery only) and
  `get-values` (a bounded range read). All write methods are excluded at the
  schema level, never exposed as tools.
- **Math-ops target** (`lambdaFunctionArn`). Pure compute over rows the
  diagnostic analyst already retrieved — no Google access, no outbound
  credentials. Operations: `sum`, `average`, `percent_change`,
  `group_by_aggregate`, `median`, `stddev`/`variance`, `correlation`,
  `min_max`, `top_n`. The diagnostic analyst always calls the Sheets-read
  target first, then feeds the returned rows to the math-ops target.

The data contract stays scoped to **one fixed spreadsheet** for this MVP —
one app-owner OAuth grant, one approved set of tabs/columns. ADR 003's
adaptive schema discovery generalizes header/alias *mapping* within that one
sheet; it does not extend to a different sheet per end user. Per-end-user
sheets remain the future multi-user work ADR 002 already deferred.

The policy itself is expressed as `docs/data-contract.yaml`: spreadsheet ID,
approved tab(s), a column→semantic-field map, the operation allow-list, and
row/column caps. It is referenced by name from the Gateway target
configuration in `agentcore.json`, so a pull request diff against this one
file shows exactly what access changed.

Each `get-values` call is capped at a fixed max rows × max columns. The
Gateway rejects any request outside the policy before contacting Google,
per ADR 002 — that boundary is not renegotiated here. What changes is who is
responsible for never hitting it in normal use: the diagnostic analyst
paginates. If it needs more data than one call's cap allows, it issues
multiple within-cap range reads and stitches the results together itself,
rather than requesting an oversized range and receiving a rejection. A
rejection should only ever indicate a bug, never legitimate large-range
demand.

## Consequences

- Two targets under one Gateway keep the "one Gateway, one Sheets boundary"
  property from ADR 002 while separating untrusted-input-shaped Sheet access
  from pure computation that needs no credentials at all.
- `docs/data-contract.yaml` is real source-of-truth policy, not just an
  agentcore.json fragment — it needs its own review discipline.
- The diagnostic analyst's read path must implement pagination/stitching
  logic; this is now a required capability, not an optional optimization.
- Swapping in the real spreadsheet later is a `docs/data-contract.yaml`
  change plus a credential provider, not a re-architecture.
