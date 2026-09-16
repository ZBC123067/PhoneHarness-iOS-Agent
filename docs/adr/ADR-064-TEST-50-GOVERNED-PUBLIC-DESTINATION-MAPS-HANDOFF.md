# ADR-064: Lower Public Destination Context into the Existing Maps Chain

Date: 2026-08-26

## Status

Accepted and device validated.

## Context

Rich Context can resolve a fresh public destination, and TEST-42.1 already has
a bounded `MapLinkAdapter`. That adapter predates TEST-45 and its original
direct trial path did not own a task-scoped Context binding or Action
Obligation. Creating a Destination Agent, Maps Router, or second Executor
would duplicate authority and weaken replay and privacy controls.

## Decision

Add a process-local `PublicDestinationBindingStore` and lower only one
`RESOLVED`, trusted, current-task `PUBLIC_DESTINATION` reference into the
existing `NativeCapabilityBridge`. The bridge must use the existing Planner,
Risk Controller, PlanExecutor, TEST-45 Ledger, MapLinkAdapter, fresh
observation, and Verifier.

The Context resolver remains non-executable. It never receives a URL. The
adapter remains the sole URL constructor. A context reference and its dispatch
binding are both one-time and are destroyed at the end of the attempt.

## Consequences

- There is no second Planner, Router, Executor, permission system, Context
  system, or Capability Registry.
- Fresh explicit task context outranks conflicting Memory, but Memory is not
  promoted into action authority.
- Untrusted OCR/visual, historical, private, stale, ambiguous, or cross-task
  data cannot dispatch.
- Predispatch rejection is governance/input evidence, not Maps method failure.
- Possible external effect without evidence becomes `UNKNOWN_SIDE_EFFECT` and
  cannot be replayed. Recovery must re-observe, refresh Context, re-plan,
  re-authorize, and re-assess Risk.
- The result proves Maps handoff only, never navigation.

## Alternatives Rejected

1. Resolver directly calls `open_url`: bypasses Planner, Risk, Executor, and
   Ledger.
2. Persist destination or generated URL: unnecessary location retention and
   replay authority.
3. Let OCR/visual/Memory independently authorize the action: violates the
   explicit current-task source boundary.
4. Retry after a lost dispatch response: can duplicate an external side
   effect.
