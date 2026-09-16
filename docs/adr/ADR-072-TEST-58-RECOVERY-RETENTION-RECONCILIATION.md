# ADR-072: Ledger-First Recovery Retention Reconciliation

Date: 2026-08-28

## Status

Accepted on host evidence. No device Gate was required or run.

## Context

TEST-56 persists restart-safe Dynamic Plan checkpoints and TEST-57 adds bounded
recovery ownership/fencing. Terminal checkpoints and expired leases need a
bounded cleanup path, but the coordinator file and TEST-45 Ledger are separate
atomic files. Treating either file's latest timestamp as authoritative could
erase evidence for an unknown external side effect or preserve a contradictory
recovery claim.

## Decision

Use deterministic Ledger-first reconciliation before cleanup:

1. read the checkpoint and lease together from the existing coordinator file;
2. read privacy-safe TEST-45 summaries scoped to the same task;
3. correlate task, capability, method, obligation, and expected Verifier refs;
4. classify conflicts, unknown outcomes, orphan artifacts, current/superseded
   revisions, terminal state, and ownership;
5. permit compare-and-delete only for an explicitly safe classification.

Cleanup removes checkpoint and lease in one existing coordinator-file atomic
replacement. It never removes TEST-45 audit evidence. The compare step rejects
a changed checkpoint digest, lease ID, or fencing token, preventing stale
cleanup decisions from deleting newer state.

Retention reconciliation is task-scoped and read-only with respect to Ledger.
TEST-57's process-start interruption reconciliation remains separate; a
retention request must not mark unrelated in-flight actions uncertain.

## Authority

- Checkpoint: reconstruction metadata, never execution truth.
- TEST-45 Ledger: action attempt and durable terminal result authority.
- Verifier correlation: semantic success authority.
- Current planning revision: supersession authority.
- TEST-57 lease/fencing: recovery ownership authority only.
- Task Coordinator: reconciliation and cleanup eligibility authority.
- Existing coordinator store: atomic compare-and-delete mechanism only.

No source grants Risk, Executor, adapter, Planner, or replay authority.

## Failure Policy

- `DISPATCHED`, `OBSERVING`, or `UNKNOWN_SIDE_EFFECT`: retain everything and do
  not retry.
- Ledger/checkpoint or Verifier/checkpoint disagreement: retain and fail closed.
- Invalid store/checkpoint: retain and fail closed.
- Active foreign lease: retain.
- Interrupted write/replace: preserve the previous valid payload.
- Expired lease: does not prove execution absence; remove only when task-scoped
  durable evidence has no ambiguous outcome.

## Consequences

- Recovery state can be explicitly bounded after verified terminal outcomes.
- Ledger audit remains bounded by the existing TEST-45 capacity and preserves
  cross-file truth after checkpoint cleanup.
- Cleanup is deterministic and idempotent.
- No cross-file transaction or physical power-loss durability is claimed.
- Automatic cleanup timing remains a later architecture decision.
- Existing TEST-49/50 behavior and TEST-51/52 fail-closed boundaries are
  unchanged.

## Alternatives Rejected

1. Latest-file-wins: timestamps cannot resolve authority or side effects.
2. Delete all terminal artifacts: may erase unknown-outcome or verifier audit.
3. New transaction database: duplicates existing persistence and recovery
   authority.
4. Immediate automatic terminal cleanup: changes restart/audit behavior before
   a lifecycle policy is approved.
5. Expired lease implies no execution: ownership is not action evidence.
6. Global Ledger interruption reconciliation during cleanup: mutates unrelated
   tasks and belongs only to process-start recovery.
