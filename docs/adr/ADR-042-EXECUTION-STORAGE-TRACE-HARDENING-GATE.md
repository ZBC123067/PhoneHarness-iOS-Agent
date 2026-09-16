# ADR-042: Execution, Storage, And Trace Hardening Gate

## Status

Accepted on 2026-08-22. TEST-40.0 implementation required.

## Decision

Before autonomous execution expands, PhoneHarness introduces three boundaries:

1. An executor-only MCP execution port. Planner, Knowledge, Memory,
   Experience, Context, and learning modules cannot use an action-capable MCP
   method.
2. A unified private storage writer for new stores with locking, atomic writes,
   recovery checks, versioning, and idempotency. Existing stores migrate in
   small verified increments.
3. A global redacted trace whose schema excludes user content, business data,
   screenshots, UI data, coordinates, actions, responses, credentials, and
   tokens.

## Rationale

The present code has a public `MCPClient.call_tool` surface, multiple local
storage write patterns, and no central privacy-safe trace contract. Existing
PlanExecutor risk checks are useful but are not a complete structural boundary.

## Consequences

- Action expansion is blocked until TEST-40.0 passes static and regression
  gates.
- Observation remains read-only and separately constrained.
- A trace is diagnostics only; it cannot authorize or replay work.
