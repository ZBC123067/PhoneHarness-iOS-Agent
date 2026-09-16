# ADR-059: Task Progress and Recovery

Date: 2026-08-25

Status: Accepted and implemented for TEST-46.

## Context

TEST-45 establishes whether one dispatched action has an uncertain side
effect. The existing Task Coordinator and Active Context Engine did not yet
have a common, privacy-safe way to identify a task that is no longer making
observable progress or to force a fresh recovery path.

## Decision

Extend the existing Task Coordinator persistence record with a small
`TaskProgressMonitor` metadata object and extend Active Context with a
recovery-required marker. No new task store, Planner, Router, Executor,
Memory system, Skill Registry, MCP endpoint, or device protocol is introduced.

The monitor stores only allow-listed state, failure category, opaque-reference
digests, counters, timestamps, and recovery generation. A detected stall moves
the task to `interrupted`, discards its in-memory session, and returns a
non-executable contract requiring:

```text
re-observe -> update context -> re-plan -> re-authorize -> re-check risk
```

The contract has `automatic_retry_allowed: false`. It contains no action
parameters and does not authorize execution. Existing runtime entry remains
responsible for its normal Planner -> Risk -> Executor -> Verifier sequence.

## Alternatives Considered

1. Add generic workflow checkpointing or event sourcing: rejected because it
   would duplicate TEST-17/18 state and permit broader retention than needed.
2. Replay the last action after a timeout: rejected because repeated actions
   can duplicate external side effects and violate TEST-45.
3. Replace the existing coordinator with LangGraph persistence: rejected as an
   unnecessary runtime dependency. Its explicit interruption and recovery
   concepts are adopted, but PhoneHarness retains its local locked stores and
   privacy schema.

## External Research

- [LangGraph fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
  supports treating stalls, retries, and interruption as explicit lifecycle
  decisions rather than implicit replay.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
  reinforces separating short-lived task state from long-term data. The
  PhoneHarness Context/Memory boundary remains unchanged.

No external framework, model, or device dependency is imported.

## Consequences

- A task can identify recoverable lack of progress without retaining private
  observation or action data.
- Progress metadata alone never re-enables execution. A fresh runtime path is
  still required, and the current test scope remains read-only.
- Active Context becomes a recovery shell only; it cannot complete while it
  advertises that fresh processing is required.
- TEST-45 continues to own uncertain side effects after dispatch; TEST-46
  consumes only opaque lifecycle evidence and cannot replace that ledger.
