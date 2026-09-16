# ADR-067: Add a Typed Dynamic Planner Contract Without Execution Authority

Date: 2026-08-28

## Status

Accepted on host evidence. No device Gate was required or run.

## Context

PhoneHarness already had a legacy `DynamicPlanner`, Capability Catalog, Skill
Registry, Method Health, Risk Controller, PlanExecutor, Verifier, and TEST-46
recovery boundary. Adding another Planner, Router, Registry, or Executor would
duplicate authority. Free-form model output also cannot safely become a device
plan, and TEST-51/52 semantic-input authorization must remain fail closed.

## Decision

Extend the existing `DynamicPlanner` with a provider-neutral typed contract:

```text
approved semantic PlannerInput
  -> typed proposal provider
  -> capability/skill dependency expansion
  -> typed DynamicPlan
  -> deterministic PlanValidator
  -> Risk Controller handoff only
```

The deterministic V1 provider selects only one uniquely matched active Skill.
The Plan records semantic capabilities, dependencies, preconditions, verifier
requirements, risk class, confirmation policy, method candidates, and bounded
replan policy. It contains no tool call, command, raw user content, MCP port,
or Executor authority.

Replanning accepts structured failure evidence only. It binds revision,
attempted methods, prior results, and context version to the previous Plan,
requires a newer observation context, never accepts `UNKNOWN_SIDE_EFFECT` for
automatic continuation, and stops after two replans.

## Deterministic Governance

`PlanValidator` rejects unknown or unavailable capabilities, missing or cyclic
dependencies, incompatible platforms, unavailable permissions/tools, missing
verifiers, unhealthy or repeated methods, stale preconditions, risk-policy
violations, high-risk steps without confirmation, retry/replan overflow, and
any attempt to bypass the Risk Controller or claim execution authority.

The TEST-52 authorization contract is preserved. Search planning requires all
five authorization facts to be direct, true, and observed on the same leaf.
Derived, unavailable, unrelated, or forged evidence remains blocked.

## Consequences

- Existing specialized Planner entry points remain compatible and unchanged.
- Capability and Skill metadata remain the source of planning truth.
- Method Health is advisory input; the Planner does not update health itself.
- A future model may propose typed candidate Skill IDs, but deterministic code
  retains validation authority.
- TEST-53 does not lower or execute a Plan. The next integration must reuse the
  existing task, Risk, Executor, and Verifier boundaries.

## Alternatives Rejected

1. Add a second Agent Planner: duplicates existing authority and contracts.
2. Let model text name tools or commands: creates an execution injection path.
3. Silently repair invalid plans: hides security and dependency failures.
4. Reuse caller-supplied replan counters: permits budget/history reset.
5. Reopen TEST-51/52 semantic authorization: contradicts current device evidence.

