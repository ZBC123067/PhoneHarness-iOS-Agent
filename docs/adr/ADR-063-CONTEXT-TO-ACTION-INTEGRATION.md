# ADR-063: Reuse the TEST-49 Launch Chain for Context-to-Action

Date: 2026-08-26

## Status

Accepted.

## Context

Rich Context can safely resolve a natural reference into a governed,
non-executable application reference. TEST-49 already proves the private,
one-time launch path through Planner, Risk Controller, PlanExecutor, TEST-45
Action Obligation Ledger, observation, and Verifier. A separate context action
path would duplicate authority and make replay or privacy errors more likely.

## Decision

Extend `InstalledAppLaunchBindingStore` with a task/workspace-scoped opaque
context reference. Let `BoundInstalledAppLaunchBridge` lower it only after a
strict `RESOLVED` Rich Context result into the existing TEST-49 one-time
binding. Consume the context reference at that point.

The resolver remains read-only. The bridge does not accept an application name
or bundle identifier from the resolved context result. It only accepts the
opaque reference and reuses the existing governed launch implementation.

## Consequences

- No Context Router, second Planner, Semantic Executor, Reference Executor, or
  second Capability Registry is introduced.
- Context references cannot be replayed after they have been lowered once.
- Recovery must create new context from fresh observation, then re-plan and
  re-authorize.
- TEST-49's existing device evidence remains limited to unique installed-app
  launch until this distinct focused gate has run.
- The design does not widen device privileges or modify RootHide, Bootstrap,
  package sources, or iOS system configuration.

## Alternatives Rejected

1. Let the resolver call an MCP action: rejected because resolution must remain
   non-executable and would bypass Risk/Executor boundaries.
2. Put the private application identifier into context: rejected because it
   leaks target identity into a longer-lived planning surface.
3. Retain reusable context action tokens: rejected because it conflicts with
   non-replayable recovery and can duplicate external effects.
