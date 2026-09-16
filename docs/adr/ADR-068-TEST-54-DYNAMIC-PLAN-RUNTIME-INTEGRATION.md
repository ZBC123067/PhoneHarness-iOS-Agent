# ADR-068: Compile Typed Plans into Existing Task Coordinator Work

Date: 2026-08-28

## Status

Accepted on host evidence. No device Gate was required or run.

## Context

TEST-53 produces validated typed `DynamicPlan` proposals with no execution
authority. The existing `TaskCoordinator` already owns task lifecycle and uses
an injected runtime facade, while `RiskController`, execution, observation,
Verifier, and TEST-46 recovery retain separate authority. Replacing any of
those components would create a second orchestration path.

The coordinator's durable schema is intentionally restricted to legacy
read-only goals. Persisting broader Dynamic Plans there would change a proven
privacy and recovery contract without a durable-runtime requirement in
TEST-54.

## Decision

Extend the existing `TaskCoordinator` with an in-memory typed-plan session and
add a deterministic `DynamicPlanRuntimeCompiler`:

```text
DynamicPlan + PlannerInput
  -> PlanValidator
  -> current Capability and Skill registry revalidation
  -> CompiledDynamicPlanStep
  -> existing TaskCoordinator
  -> existing RiskController
  -> injected executor-owned typed runtime facade
  -> Observation evidence
  -> Verifier evidence
```

`CompiledDynamicPlanStep` contains only semantic IDs, dependency IDs, registry
tools and permissions, risk metadata, method ID, and verifier requirement. It
contains no model prose, action arguments, selector, coordinate, screenshot,
raw UI, MCP response, or execution authority.

The coordinator owns an explicit step state machine, schedules a step only
after every dependency is `VERIFIED`, calls the existing `RiskController`
before the executor facade, requires typed observation and Verifier evidence,
and marks success only after verification.

## Replan and Revision Decision

Recoverable execution or verification failure creates coordinator-owned,
bounded failure metadata. The coordinator constructs the TEST-53
`PlannerFailureEvidence`; callers cannot inject arbitrary failure payloads.
Revision N+1 replaces N atomically inside the in-memory session. Calls carrying
an old plan ID or revision return `STALE_PLAN_REVISION` before executor access.
Two replans remain the maximum.

`UNKNOWN_SIDE_EFFECT` is blocked and never automatically retried or replanned.
It remains subject to the TEST-45 fresh-observation and recovery decision rule.

## Confirmation and Risk Decision

Planner risk labels never authorize work. The compiler re-reads current Skill
and Capability contracts. `RiskController` is authoritative and may require a
single-use `RiskAuthorization`. A confirmation-required step remains
`AWAITING_CONFIRMATION`, with zero executor calls, until a valid authorization
is reassessed by Risk.

High-risk action declarations are supplied only by deterministic runtime
policy keyed to a registered Skill. A high-risk Skill without such policy is
blocked by the existing Risk Controller.

## Persistence and Restart

Dynamic sessions are process-local in TEST-54. Host restart clears them, so a
former Plan cannot resume or replay. The existing read-only coordinator store
and TEST-46 persisted contracts are unchanged. Durable Dynamic Plan recovery
is not claimed.

## Consequences

- No new Planner, Executor, Risk system, Verifier, Registry, or persistence
  system is introduced.
- Existing legacy `TaskCoordinator` behavior remains backward compatible.
- TEST-51 remains blocked and TEST-52 remains fail closed before executor
  invocation when direct same-leaf authorization is absent.
- Host E2E uses a typed fake executor/observer/verifier facade. Binding compiled
  work to real capability-specific adapters and `PlanExecutor` remains a
  separate future Gate.

## Alternatives Rejected

1. Persist Dynamic Plans in the read-only coordinator schema: changes a proven
   privacy and recovery boundary without sufficient evidence.
2. Let Planner output legacy tool dictionaries: permits tool and argument
   injection.
3. Treat execution success as task success: bypasses the Verifier.
4. Reuse revision N after a replan: permits stale work to execute.
5. Automatically retry uncertain side effects: violates TEST-45.

