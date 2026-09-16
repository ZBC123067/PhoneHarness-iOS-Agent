# ADR-058: Action Obligation Ledger

Date: 2026-08-24

Status: Accepted and implemented for TEST-45.

## Context

The existing governed execution path correctly routes an action through Risk
Controller, `PlanExecutor`, the private action port, observation, and
verification. It did not persist one small, privacy-safe contract for the
period after dispatch but before verification. A lost transport response in
that interval cannot prove that the device did not receive the action.

## Decision

Add `ActionObligationLedger` as a bounded private metadata store, and make
`PlanExecutor` opt in only when an `ActionObligationRequest` is supplied.

The ledger is not a Planner, Router, Executor, task store, retry controller,
or recovery engine. It tracks this exact state machine:

```text
CREATED -> AUTHORIZED -> DISPATCHED -> OBSERVING -> VERIFIED
                |             |              |
                v             v              v
              FAILED  UNKNOWN_SIDE_EFFECT  FAILED

UNKNOWN_SIDE_EFFECT -> OBSERVING
```

The final transition is an explicit evidence-recovery transition only and
requires the `fresh_observation_started` reason code. It cannot re-dispatch
the action. `UNKNOWN_SIDE_EFFECT` therefore prohibits automatic retry and
requires a fresh observation and verification before a separate recovery
decision.

Only opaque reference identifiers, capability/method identifiers, risk class,
state, revision, timestamps, and state/reason-code audit events are stored.
The schema rejects goals, user content, tool arguments, URLs, private app
data, screenshots, OCR/AX data, coordinates, raw MCP responses, and replayable
action traces.

## Alternatives Considered

1. Keep state in process memory: rejected because a process interruption loses
   the key uncertainty evidence.
2. Add a generic event-sourcing or workflow framework: rejected because it
   would duplicate existing task, planner, retry, and persistence boundaries.
3. Adopt LangGraph checkpointing: rejected as a runtime dependency. Its
   interrupted-work and no-automatic-retry concepts are compatible, but this
   host runtime needs a smaller, privacy-restricted contract.

## External Research

- OpenAI Harness Engineering supports maintaining explicit, reviewable
  engineering boundaries instead of hidden lifecycle behavior.
- LangGraph interrupt and fault-tolerance guidance reinforces durable
  interruption state, explicit resume, and avoiding duplicate side effects.

No external framework or runtime dependency is imported.

## Consequences

- Existing callers retain their behavior unless they provide an obligation
  request; TEST-45 does not change a device action protocol or package.
- Future action owners can add their own opaque obligation request only after
  proving the method's Risk, Executor, and Verifier path.
- A storage failure before dispatch blocks execution. A storage or transport
  failure after dispatch produces `UNKNOWN_SIDE_EFFECT`, never a retry.
