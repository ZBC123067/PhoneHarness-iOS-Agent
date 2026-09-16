# ADR-071: Recovery Lease Ownership With Monotonic Fencing

Date: 2026-08-28

## Status

Accepted on host evidence. No device Gate was required or run.

## Context

TEST-56 made Dynamic Plan checkpoints restart-safe but did not coordinate two
host processes attempting to recover the same task. A process-local lock or
PID cannot provide durable ownership after process death, and adding another
recovery store would split authority from TEST-46.

## Decision

Extend the existing `CoordinatorStateStore` payload and file lock with an
optional recovery lease per Dynamic task. Each lease contains a random opaque
lease ID, hashed holder reference, bounded expiry, and monotonically increasing
fencing token. Acquisition, renewal, and stale-owner transfer occur in one
locked read-modify-atomic-replace operation.

Recovery acquires the lease only after validating the checkpoint and current
Plan contract. A recovered session revalidates and renews the lease immediately
before Executor eligibility. A prior holder whose lease was transferred cannot
persist new checkpoint state or enter Executor.

The lease grants no Risk, execution, Ledger, Observation, or Verifier authority.
TEST-45 and TEST-56 remain the sources of action-outcome and recovery truth.

## Persistence Failure Policy

The existing write, file `fsync`, and atomic replacement path is retained.
Injected write or replacement failure removes its temporary file and preserves
the last valid payload. Invalid JSON, truncated files, integrity mismatch,
unsupported schema, and missing checkpoints all fail closed.

This proves bounded host process-crash behavior. It does not prove physical
power-loss durability.

## Consequences

- TEST-46 remains the recovery architecture and the coordinator file remains
  the single recovery persistence boundary.
- Exactly one non-stale recovery owner is selected during tested concurrent
  acquisition.
- Stale transfer does not depend solely on PID.
- The fencing token is enforced at the host Executor boundary; it is not sent
  to external device services and therefore is not a distributed transaction.
- Empty ownership state does not alter legacy TEST-18/46 storage shape.
- Existing TEST-49/50 execution behavior and TEST-51/52 authorization remain
  unchanged.

## Alternatives Rejected

1. PID ownership: PID reuse and process death make it insufficient.
2. Lock held across execution: blocks unrelated persistence and does not survive
   process death as a durable ownership record.
3. Second recovery database/controller: duplicates TEST-46 authority.
4. Persisted action queue: creates replay and privacy risk.
5. Checkpoint-only ownership: checkpoint metadata cannot authorize execution.
6. Automatic retry after owner loss: may duplicate an external side effect.
