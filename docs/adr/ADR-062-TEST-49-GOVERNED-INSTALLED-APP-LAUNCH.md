# ADR-062: TEST-49 Governed Installed-App Launch

**Status:** Accepted and implemented for TEST-49

**Date:** 2026-08-26

## Context

TEST-48 remains a documentation-only provider decision: Frida observation is
deferred and no provider proof of concept is approved. The existing Apple Maps
link adapter is the sole verified native execution bridge. The next capability
must therefore be small, reusable, low-risk, and use the existing governed
execution path without adding a second Planner, Router, permission resolver,
memory store, Skill Registry, or Executor.

## Decision

Implement `BoundInstalledAppLaunchBridge`: one explicitly approved launch of
one uniquely resolved installed application.

The bridge uses the existing chain:

```text
Capability evaluation -> Intelligence Orchestration -> Dynamic Planner
-> Risk Controller -> PlanExecutor private action port -> Verifier
-> TEST-45 Action Obligation Ledger -> TEST-46 recovery handoff
```

`list_apps` is used only to create a short-lived private binding. The app
name and bundle identifier remain in an in-memory, single-use binding store.
The public plan, action ledger, method-health record, trace-safe evidence, and
result contain only aggregate target metadata, opaque binding references, and
verification booleans.

## Alternatives Considered

| Alternative | Decision | Reason |
| --- | --- | --- |
| Arbitrary URL schemes | Reject | They have open-ended external effects and less precise verification. |
| Telephone or message dispatch | Reject | They can create irreversible communication effects. |
| Shortcut or App Intent execution | Defer | Existing registries are declarative; no verified execution adapter exists. |
| Frida observation/action | Defer | TEST-48 requires a separate justified, read-only proof of concept first. |
| Installed-app foreground launch | Adopt | Uses an existing MCP tool, has one bounded foreground effect, and supports private frontmost verification. |

## Safety And Recovery

- Exact matching must yield exactly one installed candidate; ambiguity blocks.
- A runtime binding expires quickly, can be claimed once, and authorizes only
  `launch_app` for the one declared PlanExecutor step.
- Permission rejection and malformed input make zero MCP calls.
- A missing launch response becomes `UNKNOWN_SIDE_EFFECT`; it is never retried
  automatically.
- An unverified foreground result requires fresh observation and replanning.
- This bridge proves application foreground observation only. It does not
  claim any task inside the application completed.

## Consequences

The added capability is a generic controlled foreground-launch primitive,
not arbitrary application automation. It provides a device-tested execution
bridge for a later capability/method decision while preserving the existing
Risk, Verifier, Ledger, Recovery, and executor-only action-port boundaries.
