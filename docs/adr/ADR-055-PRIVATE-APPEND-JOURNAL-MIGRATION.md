# ADR-055: Private Append Journal Migration

Status: Accepted and implemented for the TEST-36 identity and consent streams
on 2026-08-24.

## Context

Several owner-local runtime stores use JSONL because their schemas are small,
auditable, and intentionally content-minimal. The pre-existing append/fsync
pattern made individual writes durable, but it did not serialize a full
read-modify-write operation across processes. In particular, two writers could
read the same final audit hash and append competing successors.

The migration must retain historical JSONL records, their schemas, consent
audit immutability, private filesystem permissions, and host-only operation.
It must not create a second Memory, Knowledge, Planner, Executor, or device
protocol.

## Research And Evaluation

1. Keep direct append/fsync writes: rejected. It cannot protect audit-chain
   ordering or other read-modify-write decisions across independent processes.
2. Migrate all private stores directly to SQLite: deferred. SQLite is a mature
   transactional reference, but a whole-store migration changes established
   schemas, recovery semantics, and test scope at once. It is not needed to
   close the immediate identity/consent race.
3. Adapt the existing private locked atomic writer pattern: selected. The
   project already uses a bounded, private, atomic writer for newer host state.
   Applying the same principles to a narrow JSONL journal preserves existing
   evidence while adding stream-level serialization and recovery.

## Decision

`PrivateAppendJournal` is the common storage primitive for the TEST-36
identity/consent streams.

- Each stream has a POSIX advisory lock, `0600` stream/lock/recovery files, and
  a `0700` private root.
- A mutation validates the complete candidate stream while holding its lock,
  atomically replaces the primary stream, and then refreshes a private recovery
  generation. The primary replacement is the commit point.
- If a primary stream is missing or invalid, readers use only a valid private
  recovery generation. Invalid, incomplete, oversized, malformed, or
  schema-invalid lines fail closed.
- Public TEST-36 policy mutations also share a root mutation lock. Consent
  audit hashes are validated and the successor hash is created in the same
  audit-stream transaction.
- JSONL record payloads remain unwrapped and schema-compatible. No raw user
  content is added by this storage layer.

## Non-Goals

- No distributed ACID transaction across identity, ownership, workspace,
  consent, and audit streams.
- No SQLite migration, RAG/vector database, cloud sync, device behavior, or
  iOS package modification.
- No automatic repair of invalid data without a valid private recovery copy.

## Validation Contract

Focused offline tests cover JSONL compatibility, append idempotency, six
independent-process writes, interrupted primary replacement, corrupt-primary
recovery, private permission enforcement, malformed/instruction-like JSONL
rejection, and concurrent TEST-36 audit-chain validation.

Subsequent P1 migrations for knowledge and lifecycle streams require their own
schema-compatibility and regression gates. They must not be declared covered by
this ADR merely because they use JSONL.

## Consequences

The immediate cross-process audit-chain race is closed without broad storage
replacement. The trade-off is whole-file replacement for bounded small streams;
larger or multi-stream transactional requirements remain a separate migration
decision.
