# ADR-044: Governed Goal Completion And Skill Evolution

- Status: Proposed; implementation requires a separate approval per phase.
- Date: 2026-08-23
- Scope: TEST-40.2 architecture integration.

## Context

PhoneHarness has independently validated modules for planning, declarative
Skills, capability evaluation, routing, teaching, consent, execution,
observation, verification, context, memory, experience, and trace. Adding new
"universal", "skill intelligence", or "teaching" systems in parallel would
create conflicting authority and an unsafe alternate device path.

## Decision

1. Define Universal Goal Completion Engine as the composition of existing
   runtime modules, not a new executor or planner.
2. Retain one declarative Skill Registry and extend it through TEST-40.3
   manifests, provenance, lifecycle, and trust review.
3. Retain the existing Adaptive Intelligence Router and Human Teaching Layer;
   TEST-41 extends their recommendation contracts rather than replacing them.
4. Require all scheduled occurrences to create a fresh task/context and flow
   through the existing permission, planning, risk, execution, observation, and
   verification path.
5. Treat cloud reasoning as an approval-governed escalation. It cannot execute
   actions, replace private knowledge, or bypass Risk/Verifier.
6. Keep Technology Radar proposal-only. Research never changes production code
   without an ACP, tests, and human approval.

## Consequences

### Positive

- Existing DEVICE_PASS boundaries remain meaningful.
- External Skills and scheduled work have a deterministic trust and revocation
  point before they gain eligibility.
- Human teaching remains controlled and cannot turn private operation history
  into replay scripts.
- The iOS experience layer can evolve later without becoming the intelligence
  authority.

### Costs

- External Skill installation and autonomous workflow execution are delayed.
- Scheduled task delivery must tolerate iOS background deferral or absence.
- A cloud approval interaction will be required before any future cloud call
  unless a later low-risk policy is explicitly approved.

## Rejected Alternatives

1. A second universal agent orchestration engine: rejected because it would
   duplicate Task Coordinator, Planner, and Executor authority.
2. An external Skill marketplace/runtime in TEST-40.3: rejected because it
   introduces code supply-chain and permission risk before a trust gate exists.
3. Direct model-to-device or scheduler-to-device calls: rejected because they
   bypass Risk Controller, Plan Executor, and Verifier.
4. Guaranteed timed iOS automation: rejected because iOS controls background
   execution timing.

## Compatibility

No existing TEST-11 through TEST-40.1 module boundary is changed. The decision
does not alter iOS code, RootHide, ElleKit, Bootstrap, package sources, device
configuration, or completed device-test evidence.

## Approval Required

This ADR authorizes architecture planning only. Every later implementation
phase requires explicit acceptance criteria and its own static/regression/device
classification.
