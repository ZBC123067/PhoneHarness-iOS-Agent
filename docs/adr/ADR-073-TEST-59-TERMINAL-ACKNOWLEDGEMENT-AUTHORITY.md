# ADR-073: Terminal Acknowledgement Authority

Date: 2026-08-29

## Status

Accepted on host evidence. No device Gate was required or run.

## Context

TEST-58 can conservatively classify recovery artifacts as safe for retention
cleanup, but classification alone does not answer when the task lifecycle has
been explicitly finalized. Automatic cleanup at the first terminal-looking
checkpoint could shorten restart auditability, confuse task confirmation with
terminal acknowledgement, or erase recovery metadata before the coordinator
has finalized the whole task.

## Decision

Add a minimal TaskCoordinator-owned lifecycle record in the existing atomic
CoordinatorStateStore:

```text
ACTIVE
-> ACKNOWLEDGEMENT_PENDING
-> RETENTION_ELIGIBLE
-> CLOSED
```

The TaskCoordinator may create a terminal candidate only from current TEST-58
reconciliation. A separate explicit acknowledgement moves the candidate to
retention eligibility. Cleanup then reruns TEST-58 reconciliation and closes
the lifecycle only after cleanup succeeds or the artifacts are already safely
cleaned.

The acknowledgement ID is bounded, hashed, and stored only as a digest. It is
not action confirmation and grants no Risk, Executor, Planner, adapter,
Verifier, or recovery authority.

## Authority Separation

- Verifier: semantic step success.
- Ledger: durable governed action outcome.
- TaskCoordinator: whole-task terminal classification and acknowledgement.
- Recovery/TEST-58: conservative reconstruction and retention reconciliation.
- CoordinatorStateStore: atomic metadata persistence only.

Terminal success requires all correlated step success; Executor success alone
is insufficient. Unknown external outcomes, evidence conflicts, active
replanning, and pending confirmation remain nonterminal for cleanup purposes.

## Compatibility

The lifecycle map is optional in the existing store schema, preserving old
payloads and TEST-58 maintenance fixtures. Once a task has a TEST-59 lifecycle
record, lower-level task cleanup also checks that record and fails closed until
it is `RETENTION_ELIGIBLE`.

Replanning resets an existing lifecycle record to the new active revision.
Cancellation records intent to stop future work but preserves possible side
effects and cannot make unknown evidence cleanable.

## Failure Policy

- Stale revision acknowledgement: reject.
- Different acknowledgement after one is recorded: reject.
- Duplicate matching acknowledgement: idempotent.
- Cleanup I/O failure: retain terminal acknowledgement and report
  infrastructure failure separately.
- Ledger/Verifier conflict: no terminal success and no cleanup.
- Unknown side effect: no acknowledgement eligibility, cleanup, or replay.

## Alternatives Rejected

1. Immediate cleanup on `DONE`: confuses session status with correlated
   terminal evidence and explicit lifecycle intent.
2. User confirmation equals acknowledgement: action authorization and terminal
   lifecycle finalization have different meanings.
3. New task database/state machine: duplicates TaskCoordinator and the existing
   atomic store.
4. Checkpoint-only terminal authority: checkpoint is reconstruction metadata,
   not execution or verification truth.
5. Cleanup failure reopens task: infrastructure failure must not alter semantic
   success/failure or trigger duplicate execution.

## Consequences

- Task cleanup has an explicit, auditable precondition.
- Terminal outcome, acknowledgement, and retention are independently visible.
- Existing recovery and execution authorities remain unchanged.
- No automatic cleanup scheduler or UI is introduced.
- TEST-49/50 semantics and TEST-51/52 fail-closed boundaries remain unchanged.
