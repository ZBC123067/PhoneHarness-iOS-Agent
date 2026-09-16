# ADR-069: Bind Dynamic Steps to Existing Governed Capability Routes

Date: 2026-08-28

## Status

Accepted on host evidence. No device Gate was required or run.

## Context

TEST-54 stopped at an injected typed runtime facade. Existing production
routes already had capability-specific translators, `PlanExecutor`, TEST-45
Ledger, observation, Verifier, and TEST-47 Method Health metadata. Calling the
TEST-49/50 high-level bridges from a Dynamic Plan would repeat Planner and
Orchestration work; introducing a generic tool/argument executor would bypass
the safety architecture.

## Decision

Add one narrow `GovernedCapabilityBindingRuntime` that maps a registered
Dynamic capability ID to a fixed existing implementation route. It accepts
only frozen capability-specific argument types and stores them in a
process-local one-time binding scoped to task, Plan revision, step, and context
version.

Immediately before execution, the existing TaskCoordinator asks the binding
runtime to revalidate the current Capability, Skill, Method, platform,
permission, dependency, target freshness, and revision contracts. The
Coordinator performs its existing Risk assessment. The binding runtime then
submits one structured plan to the existing `PlanExecutor`, which reassesses
Risk and exclusively owns Ledger, MCP dispatch, observation, and Verifier.

The initial deterministic routes are deliberately limited to existing
contracts: read-only observation, `MapLinkAdapter`, and the private one-time
installed-app binding. No semantic input or TEST-51/52 route exists.

## Correlation Decision

Execution results are cached only for the process-local task lifecycle and are
bound to Plan ID, planning revision, step ID, capability ID, method ID, and the
TEST-45 obligation. Observation and verification evidence use separate opaque
references. Cross-plan, cross-step, cross-task, stale, or unrelated evidence
cannot establish success.

## Consequences

- Existing `PlanExecutor`, TEST-45 Ledger, Risk Controller, Verifier,
  `MapLinkAdapter`, app binding store, Capability Catalog, Skill Registry, and
  Method Registry are reused.
- Adapter choice is deterministic and cannot be supplied by Planner/model
  output.
- Execution-time governance changes block without a transport call.
- Verifier failure remains a typed replan handoff even after successful
  dispatch.
- Synthetic host results do not change Method Health.
- Existing TEST-49/50 route behavior is unchanged; their DEVICE_PASS evidence
  is neither expanded nor invalidated.

## Alternatives Rejected

1. A `DynamicPlanExecutor`: duplicates `PlanExecutor` and its private MCP port.
2. Calling TEST-49/50 bridges directly: repeats Planner/Orchestration layers.
3. A generic adapter registry selected by strings: enables adapter injection.
4. Generic `tool_name + args`: turns model data into execution authority.
5. Treating dispatch success as completion: bypasses the existing Verifier.
6. Persisting typed targets or action parameters: creates replay and privacy
   risk without a durable-runtime requirement.

