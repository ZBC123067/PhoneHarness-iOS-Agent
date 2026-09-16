# ADR-070: Extend TEST-46 Storage for Dynamic Plan Recovery

Date: 2026-08-28

## Status

Accepted on host evidence. No device Gate was required or run.

## Context

TEST-54 Dynamic sessions were intentionally process-local. TEST-55 added the
governed execution chain, but a restart still discarded Plan progress and
one-time capability bindings. Persisting live adapters, action arguments, or
an Executor program counter would create replay and privacy risk. Adding a
second recovery database/controller would duplicate TEST-46 and split state
authority.

## Decision

Extend the existing `CoordinatorStateStore` payload, lock, private permissions,
and atomic replacement with an optional typed Dynamic Plan checkpoint map.
Persist only validated semantic lifecycle metadata. On restart, require the
current typed Plan and Planner input, recompile against current registries,
reconcile TEST-45 Ledger state, recheck Method Health and Risk, and recreate a
process-local capability binding from fresh typed inputs.

A SHA-256 digest provides deterministic record-integrity detection; it is not
claimed as authentication against an attacker who can rewrite the local file.
Current Registry, Ledger, Risk, and Verifier correlation prevents a recomputed
checkpoint from granting authority by itself.

If dispatch may have occurred but verification is absent, recovery returns
`EXECUTION_OUTCOME_UNKNOWN` and prohibits replay. A durable, correlated
`VERIFIED` step is restored without execution. Legacy TEST-54 fake runtimes
that lack TEST-45 evidence keep their live host behavior but their checkpoint
is conservatively downgraded to replan-required rather than forged durable
success.

## Consequences

- TEST-46 remains the recovery architecture and the coordinator file remains
  the single task/recovery persistence boundary.
- Checkpoint, Ledger, Verifier, Risk, and Registry retain separate authority.
- Empty TEST-56 state does not change legacy TEST-18/46 persisted JSON.
- Side-effect parameters and secrets cannot survive restart; callers must
  provide fresh authorized typed input or receive `USER_INPUT_REQUIRED`.
- Existing TEST-49/50 route semantics are unchanged.
- TEST-51/52 remains fail closed.

## Alternatives Rejected

1. Serialize `_DynamicPlanSession`: includes live structures and blurs trust.
2. Persist adapter objects/arguments: creates a replay-capable action queue.
3. Add a recovery database/controller: duplicates TEST-46 ownership.
4. Resume from a serialized program counter: ignores changed reality.
5. Retry every non-VERIFIED step: duplicates uncertain external effects.
6. Treat checkpoint digest as authorization: a digest is consistency evidence,
   not current Risk, Registry, Ledger, or Verifier authority.
